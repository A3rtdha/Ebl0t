"""Valorant: /finish, OCR scoreboard, wizard исхода, обновление Custom ELO."""

import asyncio
import logging
from collections import defaultdict

import disnake
from disnake.ext import commands

from modules.valorant.services import (
    aftermatch_voices,
    match_manager,
    match_roster,
    result_flow_cleanup,
    screenshot_parser,
)
from modules.valorant.services.manual_scoreboard import MANUAL_FORMAT_HELP
from modules.valorant.services.result_flow_state import (
    active_result_channels,
    wizard_sessions,
)
from modules.valorant.ui.finish_views import ManualFallbackView, OcrReviewView, ParseFailView
from shared import ui_theme

log = logging.getLogger(__name__)


class MatchCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name="finish", description="Завершить матч и загрузить скриншот результатов")
    async def finish_match(self, inter: disnake.ApplicationCommandInteraction):
        match_data = match_manager.get_active_match(inter.author.id)
        if not match_data:
            all_matches = match_manager.get_all_active_matches()
            for host_id_str, md in all_matches.items():
                if inter.author.id in md.get("team1_ids", []) + md.get("team2_ids", []):
                    return await inter.response.send_message(
                        f"❌ Ты участник матча, но не хост. "
                        f"Попроси хоста (<@{md['host_id']}>) завершить матч командой `/finish`.",
                        ephemeral=True,
                    )
            return await inter.response.send_message("❌ Нет активного матча.", ephemeral=True)

        await _regroup_voice_channels(inter.guild, match_data)

        dash_id = match_data.get("dashboard_msg_id")
        dash_ch = match_data.get("text_channel_id") or inter.channel.id
        if dash_id:
            ch = inter.guild.get_channel(dash_ch) or inter.channel
            await result_flow_cleanup.delete_message_ids(ch, [dash_id])

        match_manager.remove_active_match(inter.author.id)

        listener: ScreenshotListener = self.bot.get_cog("ScreenshotListener")
        if listener:
            listener.register(
                channel_id=inter.channel.id,
                host_id=inter.author.id,
                match_data=match_data,
                guild=inter.guild,
            )

        embed = ui_theme.brand_embed(
            title="📸  Загрузи скриншот результатов",
            description=(
                "Прикрепи **скриншот таблицы (scoreboard)** из Valorant "
                "к следующему сообщению в этом чате.\n"
                f"{ui_theme.DIVIDER}\n"
                "▸ Бот распознает статистику игроков\n"
                "▸ Ты выберешь **победителя** и **счёт**\n"
                "▸ Custom ELO обновится автоматически\n\n"
                "Нет скриншота? Жми **«Ввести вручную»**."
            ),
            color=ui_theme.COLOR_WARN,
        )
        view = ManualFallbackView(
            host=inter.author, channel=inter.channel, match_data=match_data, bot=self.bot,
        )
        await inter.response.send_message(embed=embed, view=view)
        try:
            finish_msg = await inter.original_response()
            result_flow_cleanup.track(inter.channel.id, finish_msg)
        except Exception:
            pass


async def _regroup_voice_channels(guild: disnake.Guild, match_data: dict):
    vc_ids = [match_data.get("team1_vc"), match_data.get("team2_vc")]
    team_vcs = []
    for cid in vc_ids:
        if not cid:
            continue
        ch = guild.get_channel(cid)
        if isinstance(ch, disnake.VoiceChannel):
            team_vcs.append(ch)

    members = []
    for ch in team_vcs:
        members.extend(ch.members)

    regroup = None
    if members:
        try:
            regroup = await aftermatch_voices.move_players_after_finish(guild, match_data, members)
        except Exception as e:
            log.warning(f"Не удалось перенести игроков в aftermatch: {e}")

    for ch in team_vcs:
        try:
            await ch.delete()
        except Exception:
            pass

    return regroup


class ScreenshotListener(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending: dict[int, dict] = {}
        self._ocr_generation: dict[int, int] = {}
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._handled_message_ids: set[int] = set()

    def ocr_session(self, channel_id: int) -> int:
        return self._ocr_generation.get(channel_id, 0)

    def register(self, channel_id: int, host_id: int, match_data: dict, guild):
        self.unregister(channel_id)
        self._ocr_generation[channel_id] = self._ocr_generation.get(channel_id, 0) + 1
        active_result_channels.discard(channel_id)
        wizard_sessions.pop(channel_id, None)
        self.pending[channel_id] = {
            "host_id": host_id,
            "match_data": match_data,
            "guild": guild,
        }

    def unregister(self, channel_id: int):
        self.pending.pop(channel_id, None)

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        if message.author.bot:
            return
        if message.id in self._handled_message_ids:
            return

        ch_id = message.channel.id
        lock = self._locks[ch_id]

        async with lock:
            if message.id in self._handled_message_ids:
                return
            pending = self.pending.get(ch_id)
            if not pending or message.author.id != pending["host_id"]:
                return

            image_att = next(
                (a for a in message.attachments if a.content_type and a.content_type.startswith("image/")),
                None,
            )
            if image_att is None:
                return

            self._handled_message_ids.add(message.id)
            result_flow_cleanup.track(ch_id, message)
            if len(self._handled_message_ids) > 500:
                self._handled_message_ids.clear()

            pending_data = self.pending.pop(ch_id, None)
            if not pending_data:
                return
            ocr_session = self._ocr_generation.get(ch_id, 0)

            status = await message.channel.send(
                "🔍 Анализирую скриншот... подожди несколько секунд."
            )
            result_flow_cleanup.track(ch_id, status)

            try:
                image_bytes = await image_att.read()
                content_type = image_att.content_type or "image/png"
                parsed = await screenshot_parser.parse_screenshot(
                    image_bytes, content_type
                )

                if self._ocr_generation.get(ch_id) != ocr_session:
                    await status.delete()
                    return

                if parsed is None:
                    return await status.edit(
                        content=(
                            "❌ Не удалось распознать скриншот.\n"
                            "Введи данные **вручную** — кнопка ниже.\n\n"
                            f"{MANUAL_FORMAT_HELP}"
                        ),
                        view=ParseFailView(
                            host=message.author,
                            channel=message.channel,
                            guild=pending_data["guild"],
                            match_data=pending_data["match_data"],
                            bot=self.bot,
                        ),
                    )

                await status.delete()

                severity, roster_msg = match_roster.check_screenshot_vs_lobby(
                    pending_data["match_data"], parsed,
                )
                if severity == "block":
                    return await message.channel.send(
                        embed=ui_theme.brand_embed(
                            title="⚠️  Состав не сходится",
                            description=roster_msg,
                            color=ui_theme.COLOR_DANGER,
                        ),
                        view=ParseFailView(
                            host=message.author,
                            channel=message.channel,
                            guild=pending_data["guild"],
                            match_data=pending_data["match_data"],
                            bot=self.bot,
                        ),
                    )

                preview_lines = []
                for p in parsed.get("players", [])[:12]:
                    preview_lines.append(
                        f"`{(p.get('riot_id') or '?')}` "
                        f"{p.get('kills', 0)}/{p.get('deaths', 0)}/{p.get('assists', 0)} "
                        f"ACS:{p.get('acs', 0)}"
                    )
                preview = ui_theme.brand_embed(
                    title="👀  Проверь распознавание",
                    description=(
                        "Сверь ники и статистику со скриншотом.\n"
                        "✅ **Всё верно** — дальше выбор победителя и счёта\n"
                        "✏️ **Исправить вручную** — если OCR ошибся"
                    ),
                    color=ui_theme.COLOR_WARN,
                )
                preview.add_field(
                    name="Распознано",
                    value="\n".join(preview_lines) or "—",
                    inline=False,
                )
                exp = match_roster.lobby_player_count(pending_data["match_data"])
                preview.add_field(
                    name="Состав кастомки",
                    value=f"**{exp}** чел. ({match_roster.lobby_roster_label(pending_data['match_data'])})",
                    inline=True,
                )
                if severity == "warn" and roster_msg:
                    preview.add_field(name="⚠️ Внимание", value=roster_msg, inline=False)

                preview_msg = await message.channel.send(
                    embed=preview,
                    view=OcrReviewView(
                        host=message.author,
                        channel=message.channel,
                        guild=pending_data["guild"],
                        parsed=parsed,
                        match_data=pending_data["match_data"],
                        bot=self.bot,
                        ocr_session=ocr_session,
                    ),
                )
                result_flow_cleanup.track(ch_id, preview_msg)

            except Exception as e:
                log.exception("Ошибка при обработке скриншота")
                await status.edit(
                    content=f"❌ Внутренняя ошибка: `{e}`",
                    view=ParseFailView(
                        host=message.author,
                        channel=message.channel,
                        guild=pending_data["guild"],
                        match_data=pending_data["match_data"],
                        bot=self.bot,
                    ),
                )


def setup(bot):
    bot.add_cog(MatchCog(bot))
    bot.add_cog(ScreenshotListener(bot))

"""
match_cog.py — завершение матча и обработка результатов.

Полный флоу:
1. Хост вызывает /finish
2. Бот удаляет ГК команд, сохраняет match_data в ScreenshotListener
3. Хост прикрепляет скриншот scoreboard-а в чат
4. Бот парсит скриншот через Claude Vision (K/D/A, ACS, победитель)
5. Игроки, у которых есть /link — матчатся автоматически по Riot ID
6. Участники кастомки без /link — по одному сообщению: «Кто на скрине — это @Name?»
   Выпадающий список = ники с скрина. Левые ники (не из кастомки) не спрашиваем.
7. После сопоставления всех (или пропуска) — Riot ID автоматически
   сохраняется в БД (как /link без ранга), ELO обновляется, публикуется
   финальный embed.
"""

import disnake
from disnake.ext import commands
from utils import match_manager, db_manager, elo_engine, screenshot_parser, riot_api, guild_setup, ui_theme
from ui.modals import ManualScoreboardModal
from ui.match_outcome import prompt_match_outcome, team_label
from utils.manual_scoreboard import parsed_to_manual_text, MANUAL_FORMAT_HELP
from utils import result_flow_cleanup
import asyncio
import logging
import uuid
from collections import defaultdict

log = logging.getLogger(__name__)

# Один активный флоу результата на канал (OCR → исход → wizard → ELO)
_result_flow_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_active_result_channels: set[int] = set()
_wizard_sessions: dict[int, str] = {}


# ══════════════════════════════════════════════════════════════════════
# /finish — точка входа
# ══════════════════════════════════════════════════════════════════════

class MatchCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name="finish", description="Завершить матч и загрузить скриншот результатов")
    async def finish_match(self, inter: disnake.ApplicationCommandInteraction):
        match_data = match_manager.get_active_match(inter.author.id)
        if not match_data:
            # Ищем — вдруг этот юзер участник матча, но не хост
            all_matches = match_manager.get_all_active_matches()
            for host_id_str, md in all_matches.items():
                if inter.author.id in md.get("team1_ids", []) + md.get("team2_ids", []):
                    return await inter.response.send_message(
                        f"❌ Ты участник матча, но не хост. "
                        f"Попроси хоста (<@{md['host_id']}>) завершить матч командой `/finish`.",
                        ephemeral=True,
                    )
            return await inter.response.send_message("❌ Нет активного матча.", ephemeral=True)

        # Собираем игроков из командных каналов в один «регруп»-канал,
        # чтобы лобби не разваливалось после /finish
        await _regroup_voice_channels(inter.guild, match_data)

        match_manager.remove_active_match(inter.author.id)

        # Регистрируем ожидание скриншота
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


# ══════════════════════════════════════════════════════════════════════
# Перенос игроков в общий канал после /finish (вместо удаления)
# ══════════════════════════════════════════════════════════════════════

async def _regroup_voice_channels(guild: disnake.Guild, match_data: dict):
    """
    После /finish переносим всех из командных каналов в один канал
    «перегруппировки», затем удаляем опустевшие командные каналы.
    Так лобби не разваливается — все остаются вместе.
    """
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
            category, _, _ = await guild_setup.get_or_create_hub(guild)
            lobby_id = match_data.get("lobby_id", "")
            regroup = await guild.create_voice_channel(
                name=f"🔁 Лобби #{lobby_id}", category=category,
            )
            for m in members:
                try:
                    await m.move_to(regroup)
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"Не удалось создать регруп-канал: {e}")

    # Удаляем теперь уже пустые командные каналы
    for ch in team_vcs:
        try:
            await ch.delete()
        except Exception:
            pass

    return regroup


# ══════════════════════════════════════════════════════════════════════
# Кнопка «Ввести вручную» — fallback
# ══════════════════════════════════════════════════════════════════════

class ManualFallbackView(disnake.ui.View):
    def __init__(self, host: disnake.Member, channel, match_data: dict, bot):
        super().__init__(timeout=600)
        self.host = host
        self.channel = channel
        self.match_data = match_data
        self.bot = bot

    @disnake.ui.button(label="✏️ Ввести вручную", style=disnake.ButtonStyle.secondary)
    async def manual_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост может завершить матч.", ephemeral=True)
        listener = inter.bot.get_cog("ScreenshotListener")
        if listener:
            listener.unregister(inter.channel.id)
        self.stop()
        await inter.response.send_modal(
            ManualScoreboardModal(
                inter.bot, self.channel, self.host, inter.guild, self.match_data,
            )
        )


class OcrReviewView(disnake.ui.View):
    """Превью после OCR: подтвердить или открыть ручное редактирование."""

    def __init__(self, host, channel, guild, parsed: dict, match_data: dict, bot, ocr_session: int = 0):
        super().__init__(timeout=600)
        self.host = host
        self.channel = channel
        self.guild = guild
        self.parsed = parsed
        self.match_data = match_data
        self.bot = bot
        self.ocr_session = ocr_session
        self._done = False

    def _stale(self) -> bool:
        listener = self.bot.get_cog("ScreenshotListener")
        if not listener:
            return False
        return listener.ocr_session(self.channel.id) != self.ocr_session

    async def _reject_stale(self, inter: disnake.MessageInteraction) -> bool:
        if self._stale():
            self.stop()
            await inter.response.send_message(
                "Это превью устарело — обработан другой скрин или матч уже идёт дальше.",
                ephemeral=True,
            )
            return True
        return False

    @disnake.ui.button(label="✅ Всё верно", style=disnake.ButtonStyle.green)
    async def confirm_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост.", ephemeral=True)
        if self._done or await self._reject_stale(inter):
            return
        self._done = True
        self.stop()
        listener = inter.bot.get_cog("ScreenshotListener")
        if listener:
            listener.unregister(inter.channel.id)
        await inter.response.edit_message(content="✅ Дальше — выбор победителя и счёта…", view=None)
        await prompt_match_outcome(
            self.channel, self.host, self.guild,
            self.parsed, self.match_data, self.bot,
        )

    @disnake.ui.button(label="✏️ Исправить вручную", style=disnake.ButtonStyle.primary)
    async def edit_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост.", ephemeral=True)
        if self._done or await self._reject_stale(inter):
            return
        self._done = True
        self.stop()
        prefill = parsed_to_manual_text(self.parsed)
        await inter.response.send_modal(
            ManualScoreboardModal(
                inter.bot, self.channel, self.host, inter.guild,
                self.match_data, initial_text=prefill,
            )
        )

    @disnake.ui.button(label="❌ Отмена", style=disnake.ButtonStyle.secondary)
    async def cancel_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост.", ephemeral=True)
        if self._done:
            return
        self._done = True
        self.stop()
        listener = inter.bot.get_cog("ScreenshotListener")
        if listener:
            listener.unregister(inter.channel.id)
        await inter.response.edit_message(content="❌ Обработка отменена.", view=None)


class ParseFailView(disnake.ui.View):
    def __init__(self, host, channel, guild, match_data: dict, bot):
        super().__init__(timeout=600)
        self.host = host
        self.channel = channel
        self.guild = guild
        self.match_data = match_data
        self.bot = bot

    @disnake.ui.button(label="✏️ Ввести scoreboard вручную", style=disnake.ButtonStyle.primary)
    async def manual_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост.", ephemeral=True)
        self.stop()
        listener = inter.bot.get_cog("ScreenshotListener")
        if listener:
            listener.unregister(inter.channel.id)
        await inter.response.send_modal(
            ManualScoreboardModal(
                inter.bot, self.channel, self.host, inter.guild, self.match_data,
            )
        )


# ══════════════════════════════════════════════════════════════════════
# Listener — ждёт скриншот в чате от хоста
# ══════════════════════════════════════════════════════════════════════

class ScreenshotListener(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # {channel_id: {"host_id", "match_data", "guild"}}
        self.pending: dict[int, dict] = {}
        self._ocr_generation: dict[int, int] = {}
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._handled_message_ids: set[int] = set()

    def ocr_session(self, channel_id: int) -> int:
        return self._ocr_generation.get(channel_id, 0)

    def register(self, channel_id: int, host_id: int, match_data: dict, guild):
        self.unregister(channel_id)
        self._ocr_generation[channel_id] = self._ocr_generation.get(channel_id, 0) + 1
        _active_result_channels.discard(channel_id)
        _wizard_sessions.pop(channel_id, None)
        self.pending[channel_id] = {
            "host_id":    host_id,
            "match_data": match_data,
            "guild":      guild,
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
                image_bytes  = await image_att.read()
                content_type = image_att.content_type or "image/png"
                parsed       = await screenshot_parser.parse_screenshot(
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


# ══════════════════════════════════════════════════════════════════════
# Флоу обработки результатов
# ══════════════════════════════════════════════════════════════════════

async def _start_result_flow(channel, host, guild, parsed: dict, match_data: dict, bot=None):
    """
    Точка входа после успешного парсинга.
    Разделяет игроков на «опознанных» и «неопознанных»,
    запускает поочерёдный dropdown для неопознанных.
    """
    ch_id = channel.id
    flow_lock = _result_flow_locks[ch_id]
    if flow_lock.locked():
        try:
            await channel.send(
                "⚠️ Этот матч уже обрабатывается — дождись завершения или отмени лишние сообщения.",
                delete_after=20,
            )
        except Exception:
            pass
        return

    async with flow_lock:
        if ch_id in _active_result_channels:
            return
        _active_result_channels.add(ch_id)
        try:
            await _start_result_flow_locked(channel, host, guild, parsed, match_data, bot)
        except Exception:
            _active_result_channels.discard(ch_id)
            _wizard_sessions.pop(ch_id, None)
            raise


def _normalize_host_relative_teams(parsed: dict, host, match_data: dict) -> dict:
    """
    OCR/Gemini видят scoreboard с точки зрения хоста:
    attack = союзники хоста, defense = враги. Для ELO переводим это в реальные
    стороны матча, сохранённые при старте кастомки.
    """
    if not parsed.get("teams_relative_to_host"):
        return parsed

    host_id = getattr(host, "id", None)
    team1_ids = set(match_data.get("team1_ids", []))
    team2_ids = set(match_data.get("team2_ids", []))
    team1_side = match_data.get("team1_side", "attack")
    team2_side = "defense" if team1_side == "attack" else "attack"

    if host_id in team1_ids:
        ally_side, enemy_side = team1_side, team2_side
    elif host_id in team2_ids:
        ally_side, enemy_side = team2_side, team1_side
    else:
        return parsed

    side_map = {"attack": ally_side, "defense": enemy_side}
    normalized = dict(parsed)
    normalized["players"] = [
        {**p, "team": side_map.get(p.get("team"), p.get("team"))}
        for p in parsed.get("players", [])
    ]
    if parsed.get("winner") in side_map:
        normalized["winner"] = side_map[parsed["winner"]]
    normalized["teams_relative_to_host"] = False
    return normalized


async def _start_result_flow_locked(channel, host, guild, parsed: dict, match_data: dict, bot=None):
    parsed = _normalize_host_relative_teams(parsed, host, match_data)
    players_raw: list[dict] = parsed.get("players", [])
    team1_ids   = match_data.get("team1_ids", [])
    team2_ids   = match_data.get("team2_ids", [])
    all_ids     = team1_ids + team2_ids

    # Все участники матча из БД
    linked = db_manager.get_players_bulk(all_ids)

    # Автоматическое сопоставление по Riot ID
    auto_matched: dict[int, dict] = screenshot_parser.match_players_to_discord(players_raw, linked)

    # Победитель относительно хоста: смотрим надпись «Победа»/«Поражение» и команду хоста
    host_won = parsed.get("host_won")
    host_id = getattr(host, "id", None)
    if host_won is not None and host_id is not None and host_id in auto_matched:
        host_team = auto_matched[host_id].get("team")
        other_team = "defense" if host_team == "attack" else "attack"
        parsed["winner"] = host_team if host_won else other_team

    # Участники кастомки без привязки к нику (им нужно выбрать ник с скрина)
    unmatched_discord_ids = [uid for uid in all_ids if uid not in auto_matched]

    # Ники с скрина, которые ещё не привязаны ни к кому (кандидаты для выбора)
    already_matched_riot_ids = set()
    for uid, entry in linked.items():
        riot_key = f"{entry.get('riot_name','').lower()}#{entry.get('riot_tag','').lower()}"
        already_matched_riot_ids.add(riot_key)
        already_matched_riot_ids.add(entry.get("riot_name","").lower())

    unmatched_nicks = []  # [{"riot_id": str, "stats": dict}, ...]
    for p in players_raw:
        riot_id = (p.get("riot_id") or "").strip()
        riot_key = riot_id.lower()
        name_only = riot_key.split("#")[0]
        if riot_key not in already_matched_riot_ids and name_only not in already_matched_riot_ids:
            unmatched_nicks.append({
                "riot_id": riot_id,
                "stats": {
                    "team":       p.get("team"),
                    "kills":      p.get("kills", 0) or 0,
                    "deaths":     p.get("deaths", 0) or 0,
                    "assists":    p.get("assists", 0) or 0,
                    "acs":        p.get("acs", 0) or 0,
                    "hs_percent": p.get("hs_percent"),
                },
            })

    if not unmatched_discord_ids:
        # Все участники кастомки уже определены — левые ники на скрине просто не добавляем
        await _finalize_match(
            channel=channel,
            parsed=parsed,
            match_data=match_data,
            matched_stats=auto_matched,
            linked=linked,
        )
    else:
        # Один запрос на каждого участника без привязки: "Кто на скрине — это @Name?" → выбор ника
        await _matching_wizard(
            channel=channel,
            host=host,
            guild=guild,
            unmatched_discord_ids=unmatched_discord_ids,
            unmatched_nicks=unmatched_nicks,
            already_matched=auto_matched,
            parsed=parsed,
            match_data=match_data,
            linked=linked,
            bot=bot,
        )


async def _matching_wizard(
    channel, host, guild,
    unmatched_discord_ids: list,
    unmatched_nicks: list,
    already_matched: dict, parsed: dict, match_data: dict, linked: dict,
    bot=None,
):
    """
    Один запрос на каждого участника кастомки без привязки:
    «Кто на скрине — это @Name?» → выбор ника из выпадающего списка.
    Левые ники на скрине не добавляем — только сопоставляем участников.
    """
    matched_stats = dict(already_matched)
    available_nicks = list(unmatched_nicks)
    total = len(unmatched_discord_ids)
    inter_bot = bot
    session = str(uuid.uuid4())
    _wizard_sessions[channel.id] = session

    def _alive() -> bool:
        return _wizard_sessions.get(channel.id) == session

    async def process_next(idx: int):
        if not _alive():
            return
        if idx >= total:
            await _finalize_match(
                channel=channel,
                parsed=parsed,
                match_data=match_data,
                matched_stats=matched_stats,
                linked=linked,
            )
            return

        discord_id = unmatched_discord_ids[idx]
        member = guild.get_member(discord_id)
        name = member.display_name if member else str(discord_id)
        remaining = total - idx

        embed = disnake.Embed(
            title=f"👤 Кто на скрине — это **{name}**?",
            description=(
                f"Участник не привязан через `/link`.\n"
                f"**{host.mention}**, выбери ник с скриншота или пропусти.\n\n"
                f"Осталось: {remaining} из {total}"
            ),
            color=disnake.Color.blurple(),
        )

        view = PickNickView(
            host=host,
            discord_id=discord_id,
            available_nicks=available_nicks,
            wizard_session=session,
            channel_id=channel.id,
            on_pick=lambda riot_id, stats: on_picked(discord_id, riot_id, stats, idx),
            on_skip=lambda: on_skipped(idx),
        )
        msg = await channel.send(embed=embed, view=view)
        result_flow_cleanup.track(channel.id, msg)

    async def on_picked(discord_id: int, riot_id: str, stats: dict, idx: int):
        if not _alive():
            return
        matched_stats[discord_id] = stats
        # Убираем выбранный ник из списка для следующих
        for i, n in enumerate(available_nicks):
            if (n.get("riot_id") or "").strip() == riot_id.strip():
                available_nicks.pop(i)
                break

        name, tag = _split_riot_id(riot_id)
        existing = db_manager.get_player(discord_id)
        if existing is None:
            asyncio.create_task(_auto_link_with_rank(discord_id, name, tag, bot=inter_bot))
        elif existing.get("riot_name", "").lower() != name.lower():
            asyncio.create_task(_auto_link_with_rank(discord_id, name, tag, bot=inter_bot))

        await process_next(idx + 1)

    async def on_skipped(idx: int):
        if not _alive():
            return
        await process_next(idx + 1)

    await process_next(0)


def _split_riot_id(riot_id: str) -> tuple[str, str]:
    """Разбивает 'Name#TAG' на ('Name', 'TAG'). Если нет # — TAG='???'."""
    if "#" in riot_id:
        parts = riot_id.split("#", 1)
        return parts[0].strip(), parts[1].strip()
    return riot_id.strip(), "???"


async def _auto_link_with_rank(discord_id: int, name: str, tag: str, bot=None):
    """
    Фоновая задача: получает ранг через Henrik API, сохраняет /link,
    затем отправляет игроку DM с просьбой подтвердить привязку.
    """
    try:
        rank_data = await riot_api.get_player_rank(name, tag)
        if rank_data:
            db_manager.link_player(
                discord_id=discord_id,
                riot_name=name,
                riot_tag=tag,
                region="eu",
                rank=rank_data["rank"],
                rank_weight=rank_data["weight"],
                elo=rank_data["elo"],
            )
            log.info(f"Автопривязка {name}#{tag} → discord_id={discord_id}, ранг={rank_data['rank']}")
        else:
            db_manager.link_player(
                discord_id=discord_id,
                riot_name=name,
                riot_tag=tag,
                region="eu",
                rank="Unrated",
                rank_weight=0,
                elo=0,
            )
            log.info(f"Автопривязка {name}#{tag} → discord_id={discord_id} (ранг не получен)")

        # Отправляем DM игроку с запросом подтверждения
        if bot:
            await _send_link_confirmation_dm(bot, discord_id, name, tag, rank_data)

    except Exception as e:
        log.warning(f"_auto_link_with_rank failed: {e}")


async def _send_link_confirmation_dm(bot, discord_id: int, name: str, tag: str, rank_data: dict | None):
    """Отправляет личное сообщение игроку с просьбой подтвердить Riot ID."""
    try:
        user = bot.get_user(discord_id) or await bot.fetch_user(discord_id)
        if user is None:
            return

        rank_str = ""
        if rank_data:
            emoji = riot_api.rank_emoji(rank_data["rank"])
            rank_str = f"\nРанг: {emoji} **{rank_data['rank']}** ({rank_data['rr']} RR)"

        embed = disnake.Embed(
            title="🔗 Привязка аккаунта Valorant",
            description=(
                f"Хост матча указал, что ты играл под ником:\n"
                f"## `{name}#{tag}`{rank_str}\n\n"
                f"Это твой аккаунт? Если да — он автоматически привяжется к твоему Discord.\n"
                f"Если нет — нажми **«Изменить»** и укажи правильный Riot ID."
            ),
            color=disnake.Color.blurple(),
        )
        embed.set_footer(text="Привязка нужна для подсчёта Custom ELO и балансировки команд")

        view = LinkConfirmView(discord_id=discord_id, riot_name=name, riot_tag=tag, bot=bot)
        await user.send(embed=embed, view=view)

    except disnake.Forbidden:
        log.info(f"Не удалось отправить DM пользователю {discord_id} — личные сообщения закрыты")
    except Exception as e:
        log.warning(f"_send_link_confirmation_dm failed: {e}")


# ══════════════════════════════════════════════════════════════════════
# View подтверждения в DM
# ══════════════════════════════════════════════════════════════════════

class LinkConfirmView(disnake.ui.View):
    """
    Кнопки «✅ Да, всё верно» и «✏️ Изменить» в личных сообщениях игрока.
    """
    def __init__(self, discord_id: int, riot_name: str, riot_tag: str, bot):
        super().__init__(timeout=86400)  # 24 часа
        self.discord_id = discord_id
        self.riot_name  = riot_name
        self.riot_tag   = riot_tag
        self.bot        = bot

    @disnake.ui.button(label="✅ Да, это я", style=disnake.ButtonStyle.green)
    async def confirm_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        self.stop()
        # Привязка уже сохранена — просто подтверждаем
        for child in self.children:
            child.disabled = True
        await inter.response.edit_message(
            content="✅ Отлично! Аккаунт подтверждён. Теперь в следующих матчах ты будешь распознаваться автоматически.",
            embed=None,
            view=self,
        )

    @disnake.ui.button(label="✏️ Изменить", style=disnake.ButtonStyle.secondary)
    async def change_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        self.stop()
        for child in self.children:
            child.disabled = True
        await inter.response.edit_message(
            content=(
                "Укажи свой правильный Riot ID — напиши его здесь в формате `Ник#TAG`\n"
                "Например: `ProPlayer#EUW`\n\n"
                "У тебя есть **5 минут**."
            ),
            embed=None,
            view=self,
        )
        # Ждём текстового ответа в DM
        try:
            msg = await inter.bot.wait_for(
                "message",
                check=lambda m: m.author.id == self.discord_id and isinstance(m.channel, disnake.DMChannel),
                timeout=300,
            )
            riot_id = msg.content.strip()
            if "#" not in riot_id:
                await msg.reply("❌ Неверный формат. Нужно `Ник#TAG`. Попробуй `/link` в боте.")
                return

            new_name, new_tag = riot_id.split("#", 1)
            new_name = new_name.strip()
            new_tag  = new_tag.strip()

            status = await msg.reply(f"🔍 Проверяю `{new_name}#{new_tag}`...")

            rank_data = await riot_api.get_player_rank(new_name, new_tag)
            if rank_data is None:
                await status.edit(content=(
                    f"❌ Аккаунт `{new_name}#{new_tag}` не найден.\n"
                    f"Проверь правильность и попробуй `/link` в Discord-боте."
                ))
                return

            db_manager.link_player(
                discord_id=self.discord_id,
                riot_name=new_name,
                riot_tag=new_tag,
                region="eu",
                rank=rank_data["rank"],
                rank_weight=rank_data["weight"],
                elo=rank_data["elo"],
            )

            emoji = riot_api.rank_emoji(rank_data["rank"])
            await status.edit(content=(
                f"✅ Аккаунт обновлён!\n"
                f"**{new_name}#{new_tag}** {emoji} {rank_data['rank']} ({rank_data['rr']} RR)\n\n"
                f"Теперь ты будешь распознаваться автоматически в следующих матчах."
            ))

        except asyncio.TimeoutError:
            await inter.channel.send("⏰ Время вышло. Используй `/link` в Discord-боте чтобы изменить аккаунт.")

    async def on_timeout(self):
        # Просто тихо истекаем — не спамим в DM
        pass


# ══════════════════════════════════════════════════════════════════════
# UI: один запрос — выбор ника с скрина для Discord-участника
# ══════════════════════════════════════════════════════════════════════

class PickNickView(disnake.ui.View):
    """
    Один Select: ники с скрина (K/D/A в описании) + кнопка «Пропустить».
    Хост выбирает, какой ник на скрине — это данный участник.
    """
    def __init__(self, host, discord_id: int, available_nicks: list,
                 on_pick, on_skip, wizard_session: str, channel_id: int):
        super().__init__(timeout=180)
        self.host = host
        self.discord_id = discord_id
        self.available_nicks = available_nicks  # [{"riot_id", "stats"}, ...]
        self.on_pick = on_pick
        self.on_skip = on_skip
        self.wizard_session = wizard_session
        self.channel_id = channel_id
        self._responded = False
        self._add_nick_select(available_nicks)

    def _stale(self) -> bool:
        return _wizard_sessions.get(self.channel_id) != self.wizard_session

    def _add_nick_select(self, available_nicks: list) -> None:
        options = []
        for i, n in enumerate(available_nicks[:25]):
            riot_id = (n.get("riot_id") or "").strip() or "?"
            st = n.get("stats") or {}
            desc = f"K/D/A: {st.get('kills',0)}/{st.get('deaths',0)}/{st.get('assists',0)} ACS:{st.get('acs',0)}"[:100]
            options.append(disnake.SelectOption(
                label=riot_id[:100],
                value=str(i),
                description=desc,
            ))

        if options:
            select = disnake.ui.Select(
                placeholder="Выбери ник с скриншота",
                options=options,
                custom_id="pick_nick",
            )
            select.callback = self._select_callback
            self.add_item(select)

    async def _select_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост может сопоставлять игроков.", ephemeral=True)
        if self._responded or self._stale():
            if self._stale() and not self._responded:
                self._responded = True
                self.stop()
                return await inter.response.send_message(
                    "Этот шаг устарел — матч уже обработан другим сообщением.",
                    ephemeral=True,
                )
            return
        self._responded = True
        self.stop()

        idx = int(inter.values[0])
        item = self.available_nicks[idx]
        riot_id = item.get("riot_id") or ""
        stats = item.get("stats") or {}
        member = inter.guild.get_member(self.discord_id)

        await inter.response.edit_message(
            content=f"✅ {member.mention if member else self.discord_id} → `{riot_id}`",
            embed=None,
            view=None,
        )
        await self.on_pick(riot_id, stats)

    @disnake.ui.button(label="⏭ Пропустить", style=disnake.ButtonStyle.secondary, row=1)
    async def skip_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост может управлять этим.", ephemeral=True)
        if self._responded:
            return
        if self._stale():
            self._responded = True
            self.stop()
            return await inter.response.send_message(
                "Этот шаг устарел — матч уже обработан.",
                ephemeral=True,
            )
        self._responded = True
        self.stop()
        await inter.response.edit_message(
            content="⏭ Игрок пропущен, ELO не обновится.",
            embed=None,
            view=None,
        )
        await self.on_skip()

    async def on_timeout(self):
        if not self._responded and not self._stale():
            self._responded = True
            await self.on_skip()


# ══════════════════════════════════════════════════════════════════════
# Финализация: подсчёт ELO и публикация итогового embed
# ══════════════════════════════════════════════════════════════════════

async def _finalize_match(channel, parsed: dict, match_data: dict,
                          matched_stats: dict, linked: dict):
    """
    Считает ELO для всех сопоставленных игроков и публикует итог.
    matched_stats: {discord_id: {team, kills, deaths, assists, acs, hs_percent}}
    """
    try:
        await _finalize_match_body(channel, parsed, match_data, matched_stats, linked)
    finally:
        _active_result_channels.discard(channel.id)
        _wizard_sessions.pop(channel.id, None)


async def _finalize_match_body(channel, parsed: dict, match_data: dict,
                               matched_stats: dict, linked: dict):
    score_atk   = parsed.get("score_attack", "?")
    score_def   = parsed.get("score_defense", "?")
    players_raw = parsed.get("players", [])

    team1_ids  = match_data.get("team1_ids", [])
    team2_ids  = match_data.get("team2_ids", [])
    team1_side = match_data.get("team1_side", "attack")
    team2_side = "defense" if team1_side == "attack" else "attack"
    winner_side = parsed.get("winner", "?")
    winner_team = parsed.get("winner_team")

    if winner_team == 1:
        winner_ids = [uid for uid in team1_ids if uid in matched_stats]
        loser_ids = [uid for uid in team2_ids if uid in matched_stats]
        winner_label = team_label(1, match_data)
    elif winner_team == 2:
        winner_ids = [uid for uid in team2_ids if uid in matched_stats]
        loser_ids = [uid for uid in team1_ids if uid in matched_stats]
        winner_label = team_label(2, match_data)
    elif winner_side == team1_side:
        winner_ids = [uid for uid in team1_ids if uid in matched_stats]
        loser_ids = [uid for uid in team2_ids if uid in matched_stats]
        winner_label = team_label(1, match_data)
    elif winner_side == team2_side:
        winner_ids = [uid for uid in team2_ids if uid in matched_stats]
        loser_ids = [uid for uid in team1_ids if uid in matched_stats]
        winner_label = team_label(2, match_data)
    else:
        winner_ids = []
        loser_ids = list(matched_stats.keys())
        winner_label = f"Сторона: {winner_side}"

    score_winner = parsed.get("score_winner")
    score_loser = parsed.get("score_loser")
    if score_winner is None or score_loser is None:
        try:
            score_atk_int = int(score_atk) if str(score_atk).isdigit() else None
            score_def_int = int(score_def) if str(score_def).isdigit() else None
        except (ValueError, TypeError):
            score_atk_int = score_def_int = None
        if winner_team == 1 or winner_side == team1_side:
            score_winner = score_atk_int if team1_side == "attack" else score_def_int
            score_loser = score_def_int if team1_side == "attack" else score_atk_int
        elif winner_team == 2 or winner_side == team2_side:
            score_winner = score_def_int if team2_side == "defense" else score_atk_int
            score_loser = score_atk_int if team2_side == "defense" else score_def_int
        else:
            score_winner = score_loser = None

    # Обновляем ELO с новой математикой
    elo_changes = {}
    if winner_ids or loser_ids:
        elo_changes = elo_engine.update_elos_after_match(
            winner_ids=winner_ids,
            loser_ids=loser_ids,
            stats_by_id=matched_stats,
            score_winner=score_winner,
            score_loser=score_loser,
        )

    # Обновляем linked из БД (там могли появиться новые авто-привязки)
    all_ids = team1_ids + team2_ids
    linked_fresh = db_manager.get_players_bulk(all_ids)

    # ── Embed результатов ──────────────────────────────────────────────
    embed = ui_theme.brand_embed(title="🏆  Матч завершён!", color=ui_theme.COLOR_SUCCESS)
    if score_winner is not None and score_loser is not None:
        score_display = f"# {score_winner} : {score_loser}"
    else:
        score_display = f"# {score_atk} : {score_def}"
    embed.description = (
        f"🥇  **{winner_label}**\n"
        f"{score_display}\n"
        f"{ui_theme.DIVIDER}"
    )

    # Таблица по игрокам — сортируем по ACS (как в игре)
    sorted_players = sorted(players_raw, key=lambda p: p.get("acs", 0) or 0, reverse=True)
    perf_lines = []
    for p in sorted_players:
        riot_id = p.get("riot_id", "?")
        k  = p.get("kills",   0)
        d  = p.get("deaths",  0)
        a  = p.get("assists", 0)
        acs = p.get("acs",   0)
        hs  = p.get("hs_percent")
        hs_str = f" · HS {hs}%" if hs is not None else ""
        team_icon = "🔵" if p.get("team") == "attack" else "🔴"
        perf_lines.append(
            f"{team_icon} `{acs:>3}` ACS · {k}/{d}/{a}{hs_str} — **{riot_id}**"
        )

    if perf_lines:
        embed.add_field(
            name="📋  Статистика (по ACS)",
            value="\n".join(perf_lines),
            inline=False,
        )

    # ELO изменения (с отображением импакта)
    elo_lines = []
    for uid, ch in elo_changes.items():
        entry = linked_fresh.get(uid) or linked.get(uid) or {}
        name  = entry.get("riot_name") or f"<@{uid}>"
        delta = ch["delta"]
        sign  = "+" if delta >= 0 else ""
        label = elo_engine.custom_elo_to_rank_label(ch["new"])
        won   = uid in winner_ids
        result_icon = "✅" if won else "❌"
        p_m   = ch.get("perf_mult", 1.0)
        perf_emoji = "🔥" if p_m >= 1.2 else ("🥶" if p_m <= 0.8 else "🤝")
        elo_lines.append(
            f"{result_icon} `{name}`: **{ch['old']}** → **{ch['new']}** "
            f"({sign}{delta}) {label} [Импакт: {perf_emoji} {p_m}x]"
        )

    if elo_lines:
        embed.add_field(
            name="📈 Custom ELO",
            value="\n".join(elo_lines),
            inline=False,
        )

    unmatched_count = len(players_raw) - len(matched_stats)
    if unmatched_count > 0:
        embed.set_footer(
            text=f"{ui_theme.BRAND_FOOTER}  ·  ⚠️ {unmatched_count} не распознано "
                 "(попроси привязать /link заранее)"
        )

    # Записываем историю в БД
    map_name = None  # TODO: пробросить из match_data если будет храниться
    db_manager.record_match_result(
        winner_ids=winner_ids,
        loser_ids=loser_ids,
        stats_by_id=matched_stats,
        elo_changes=elo_changes,
        map_name=map_name,
    )

    await result_flow_cleanup.cleanup_channel(channel)
    await channel.send(embed=embed)


def setup(bot):
    bot.add_cog(MatchCog(bot))
    bot.add_cog(ScreenshotListener(bot))

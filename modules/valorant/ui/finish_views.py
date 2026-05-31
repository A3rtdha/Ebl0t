"""Views for /finish, OCR review, parse failure, and nick-matching wizard."""

import asyncio
import logging

import disnake

from modules.valorant.services import result_flow_cleanup
from modules.valorant.services.manual_scoreboard import parsed_to_manual_text
from modules.valorant.ui.match_outcome import prompt_match_outcome
from modules.valorant.ui.modals import ManualScoreboardModal
from modules.valorant.services.result_flow_state import wizard_sessions

log = logging.getLogger(__name__)


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


class LinkConfirmView(disnake.ui.View):
    """Кнопки «✅ Да, всё верно» и «✏️ Изменить» в личных сообщениях игрока."""

    def __init__(self, discord_id: int, riot_name: str, riot_tag: str, bot):
        super().__init__(timeout=86400)
        self.discord_id = discord_id
        self.riot_name = riot_name
        self.riot_tag = riot_tag
        self.bot = bot

    @disnake.ui.button(label="✅ Да, это я", style=disnake.ButtonStyle.green)
    async def confirm_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        self.stop()
        for child in self.children:
            child.disabled = True
        await inter.response.edit_message(
            content="✅ Отлично! Аккаунт подтверждён. Теперь в следующих матчах ты будешь распознаваться автоматически.",
            embed=None,
            view=self,
        )

    @disnake.ui.button(label="✏️ Изменить", style=disnake.ButtonStyle.secondary)
    async def change_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        from modules.valorant.services import db_manager, riot_api

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
            new_tag = new_tag.strip()

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
        pass


class PickNickView(disnake.ui.View):
    """Select ников с скрина для Discord-участника + «Пропустить»."""

    def __init__(
        self,
        host,
        discord_id: int,
        available_nicks: list,
        on_pick,
        on_skip,
        wizard_session: str,
        channel_id: int,
    ):
        super().__init__(timeout=180)
        self.host = host
        self.discord_id = discord_id
        self.available_nicks = available_nicks
        self.on_pick = on_pick
        self.on_skip = on_skip
        self.wizard_session = wizard_session
        self.channel_id = channel_id
        self._responded = False
        self._add_nick_select(available_nicks)

    def _stale(self) -> bool:
        return wizard_sessions.get(self.channel_id) != self.wizard_session

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

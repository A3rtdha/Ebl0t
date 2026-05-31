import disnake
from modules.valorant.services.manual_scoreboard import parse_manual_scoreboard, MANUAL_FORMAT_HELP


class ManualScoreboardModal(disnake.ui.Modal):
    """Ручной ввод scoreboard: счёт, победитель, строки Ник|K|D|A|ACS|сторона."""

    def __init__(
        self,
        bot,
        channel,
        host,
        guild,
        match_data: dict,
        initial_text: str | None = None,
    ):
        self.bot = bot
        self.channel = channel
        self.host = host
        self.guild = guild
        self.match_data = match_data

        default = initial_text or (
            "Ник|K|D|A|ACS|защита\n"
            "Player|10|10|5|200|атака"
        )

        components = [
            disnake.ui.TextInput(
                label="Счёт, победитель и игроки",
                placeholder="Ник|K|D|A|ACS|защита — по одной строке на игрока",
                custom_id="scoreboard",
                style=disnake.TextInputStyle.paragraph,
                value=default[:4000],
                max_length=4000,
            ),
        ]
        super().__init__(title="Ручной scoreboard", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        parsed = parse_manual_scoreboard(inter.text_values["scoreboard"])
        if parsed is None:
            return await inter.response.send_message(
                f"❌ Не разобрал текст. {MANUAL_FORMAT_HELP}",
                ephemeral=True,
            )

        listener = inter.bot.get_cog("ScreenshotListener")
        if listener:
            listener.unregister(inter.channel.id)

        await inter.response.send_message("✅ Статистика принята.", ephemeral=True)

        from modules.valorant.ui.match_outcome import prompt_match_outcome

        await prompt_match_outcome(
            self.channel, self.host, self.guild, parsed, self.match_data, self.bot,
        )

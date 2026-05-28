import disnake
from utils.match_outcome import (
    SCORE_PRESETS,
    apply_team_outcome,
    guess_score_from_parsed,
    guess_winner_team_from_parsed,
    team_label,
)


def _result_flow_busy(channel_id: int) -> bool:
    try:
        from cogs.match_cog import _active_result_channels
        return channel_id in _active_result_channels
    except ImportError:
        return False


class CustomScoreModal(disnake.ui.Modal):
    def __init__(self, parent: "MatchOutcomeView"):
        self.parent_view = parent
        components = [
            disnake.ui.TextInput(
                label="Счёт (победитель : проигравший)",
                placeholder="13:9",
                custom_id="score",
                style=disnake.TextInputStyle.short,
                max_length=10,
                value=f"{parent.score_winner}:{parent.score_loser}",
            ),
        ]
        super().__init__(title="Свой счёт", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        raw = inter.text_values["score"].strip().replace(" ", "")
        if ":" not in raw:
            return await inter.response.send_message("Формат: `13:9`", ephemeral=True)
        parts = raw.split(":", 1)
        try:
            w, l = int(parts[0]), int(parts[1])
        except ValueError:
            return await inter.response.send_message("Только числа, например `13:9`", ephemeral=True)
        if w < 0 or l < 0 or w > 30 or l > 30:
            return await inter.response.send_message("Нереалистичный счёт.", ephemeral=True)
        self.parent_view.score_winner = w
        self.parent_view.score_loser = l
        await inter.response.send_message(f"Счёт: **{w}:{l}**", ephemeral=True)


class MatchOutcomeView(disnake.ui.View):
    """Хост выбирает команду-победителя и счёт перед подсчётом ELO."""

    def __init__(self, host, channel, guild, parsed: dict, match_data: dict, bot):
        super().__init__(timeout=600)
        self.host = host
        self.channel = channel
        self.guild = guild
        self.parsed = parsed
        self.match_data = match_data
        self.bot = bot

        guess_team = guess_winner_team_from_parsed(parsed, match_data)
        guess_score = guess_score_from_parsed(parsed)
        self.winner_team: int | None = guess_team
        self.score_winner = guess_score[0] if guess_score else 13
        self.score_loser = guess_score[1] if guess_score else 9
        self._confirmed = False

        winner_opts = [
            disnake.SelectOption(
                label=team_label(1, match_data)[:100],
                value="1",
                default=(guess_team == 1),
            ),
            disnake.SelectOption(
                label=team_label(2, match_data)[:100],
                value="2",
                default=(guess_team == 2),
            ),
        ]
        winner_sel = disnake.ui.Select(
            placeholder="Победившая команда",
            options=winner_opts,
            custom_id="winner_team",
            min_values=1,
            max_values=1,
        )
        winner_sel.callback = self._winner_callback
        self.add_item(winner_sel)

        score_opts = []
        preset_val = f"{self.score_winner}:{self.score_loser}"
        for label, w, l in SCORE_PRESETS:
            score_opts.append(
                disnake.SelectOption(
                    label=label.replace(":", " : "),
                    value=f"{w}:{l}",
                    default=(f"{w}:{l}" == preset_val),
                )
            )
        score_opts.append(
            disnake.SelectOption(label="✏️ Свой счёт…", value="custom")
        )
        score_sel = disnake.ui.Select(
            placeholder=f"Счёт ({self.score_winner} : {self.score_loser})",
            options=score_opts[:25],
            custom_id="score",
            min_values=1,
            max_values=1,
            row=1,
        )
        score_sel.callback = self._score_callback
        self.add_item(score_sel)

    async def _winner_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост.", ephemeral=True)
        self.winner_team = int(inter.values[0])
        await inter.response.send_message(
            f"Победитель: **{team_label(self.winner_team, self.match_data)}**",
            ephemeral=True,
        )

    async def _score_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост.", ephemeral=True)
        val = inter.values[0]
        if val == "custom":
            return await inter.response.send_modal(CustomScoreModal(self))
        w, l = val.split(":")
        self.score_winner, self.score_loser = int(w), int(l)
        await inter.response.send_message(
            f"Счёт: **{self.score_winner} : {self.score_loser}**",
            ephemeral=True,
        )

    @disnake.ui.button(label="✅ Считать ELO", style=disnake.ButtonStyle.green, row=2)
    async def confirm(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост.", ephemeral=True)
        if self._confirmed or _result_flow_busy(self.channel.id):
            return await inter.response.send_message(
                "Матч уже считается или это окно устарело.",
                ephemeral=True,
            )
        if self.winner_team not in (1, 2):
            return await inter.response.send_message(
                "Сначала выбери **победившую команду** в списке выше.",
                ephemeral=True,
            )
        self._confirmed = True
        self.stop()
        parsed = apply_team_outcome(
            self.parsed,
            self.match_data,
            self.winner_team,
            self.score_winner,
            self.score_loser,
        )
        await inter.response.edit_message(
            content=(
                f"✅ {team_label(self.winner_team, self.match_data)} · "
                f"**{self.score_winner}:{self.score_loser}** — считаю ELO…"
            ),
            view=None,
        )
        from cogs.match_cog import _start_result_flow

        await _start_result_flow(
            channel=self.channel,
            host=self.host,
            guild=self.guild,
            parsed=parsed,
            match_data=self.match_data,
            bot=self.bot,
        )

    @disnake.ui.button(label="❌ Отмена", style=disnake.ButtonStyle.secondary, row=2)
    async def cancel(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост.", ephemeral=True)
        self.stop()
        await inter.response.edit_message(content="❌ Отменено.", view=None)


async def prompt_match_outcome(channel, host, guild, parsed: dict, match_data: dict, bot):
    guess_team = guess_winner_team_from_parsed(parsed, match_data)
    guess_score = guess_score_from_parsed(parsed)
    hint = ""
    if guess_team and guess_score:
        hint = (
            f"\n\n_С OCR: {team_label(guess_team, match_data)}, "
            f"счёт {guess_score[0]}:{guess_score[1]} — проверь и подтверди._"
        )
    from utils import ui_theme
    from utils import result_flow_cleanup

    embed = ui_theme.brand_embed(
        title="🏁  Итог матча",
        description=(
            "**1.** Выбери **команду-победителя**\n"
            "**2.** Укажи **счёт** — раунды победителя : проигравшего\n"
            "**3.** Нажми **«Считать ELO»**"
            f"{hint}"
        ),
        color=ui_theme.COLOR_WARN,
    )
    msg = await channel.send(
        embed=embed,
        view=MatchOutcomeView(host, channel, guild, parsed, match_data, bot),
    )
    result_flow_cleanup.track(channel.id, msg)

import disnake

class MatchResultModal(disnake.ui.Modal):
    def __init__(self, bot, channel_to_send):
        self.bot = bot
        self.channel_to_send = channel_to_send

        components = [
            disnake.ui.TextInput(
                label="Кто победил?",
                placeholder="Атака / Защита",
                custom_id="winner",
                style=disnake.TextInputStyle.short,
                max_length=20,
            ),
            disnake.ui.TextInput(
                label="Счет (Атака : Защита)",
                placeholder="13 : 9",
                custom_id="score",
                style=disnake.TextInputStyle.short,
                max_length=10,
            ),
            disnake.ui.TextInput(
                label="Лучший игрок (MVP)",
                placeholder="Никнейм",
                custom_id="mvp",
                style=disnake.TextInputStyle.short,
                required=False
            ),
        ]
        
        super().__init__(title="Результаты матча", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        winner = inter.text_values["winner"]
        score = inter.text_values["score"]
        mvp = inter.text_values["mvp"] or "Не указан"

        embed = disnake.Embed(title="🏆 Матч завершен!", color=disnake.Color.gold())
        embed.add_field(name="🥇 Победитель", value=f"**{winner}**", inline=True)
        embed.add_field(name="📊 Счет", value=f"**{score}**", inline=True)
        embed.add_field(name="⭐ MVP", value=f"{mvp}", inline=False)
        embed.set_footer(text=f"Матч провел: {inter.author.display_name}")
        
        await self.channel_to_send.send(embed=embed)
        
        await inter.response.send_message("✅ Результаты опубликованы!", ephemeral=True)

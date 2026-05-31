import disnake
from disnake.ext import commands
from ui.lobby_views import SetupModeView
from utils import guild_setup, network_retry, ui_theme

# Тихий тестовый флоу — только этот Discord ID
DEV_OWNER_ID = 634414560266158112


class Customs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _open_custom_setup(
        self,
        inter: disnake.ApplicationCommandInteraction,
        *,
        dev_mode: bool,
    ):
        category, _, customs_channel = await guild_setup.get_or_create_hub(inter.guild)

        if not dev_mode and inter.channel_id != customs_channel.id:
            await inter.response.send_message(
                f"**Eblot:** кастомки создаются только в {customs_channel.mention}.",
                ephemeral=True,
            )
            return

        await network_retry.retry_on_network(lambda: inter.response.defer())

        title = "🔧  DEV · Valorant Custom" if dev_mode else "🎮  Настройка Valorant Custom"
        extra = (
            f"\n{ui_theme.DIVIDER}\n"
            f"*Тихий режим: без пинга @Valorant и без анонса в сбор.*"
            if dev_mode
            else ""
        )
        embed = ui_theme.brand_embed(
            title=title,
            description=(
                f"Категория матча: **{category.name}**\n"
                f"Создавать кастомки: {customs_channel.mention} (роль Valorant).\n"
                f"{ui_theme.DIVIDER}\n"
                f"**RANDOM** — дашборд: команды, карта, агенты → START\n"
                f"**VOTED** — драфт (в разработке)\n\n"
                f"После матча хост жмёт `/finish` · ранг в лобби — `/link`"
                f"{extra}"
            ),
            color=disnake.Color.orange() if dev_mode else disnake.Color.red(),
        )

        view = SetupModeView(dev_mode=dev_mode)
        await inter.edit_original_response(embed=embed, view=view)

    @commands.slash_command(name="custom", description="Создать кастомную игру Valorant")
    async def create_custom(self, inter: disnake.ApplicationCommandInteraction):
        await self._open_custom_setup(inter, dev_mode=False)

    @commands.slash_command(
        name="dev",
        description="Тест кастомки без уведомлений другим (только владелец бота)",
    )
    async def dev_custom(self, inter: disnake.ApplicationCommandInteraction):
        if inter.author.id != DEV_OWNER_ID:
            await inter.response.send_message(
                "Команда `/dev` доступна только владельцу Eblot.",
                ephemeral=True,
            )
            return
        await self._open_custom_setup(inter, dev_mode=True)

def setup(bot):
    bot.add_cog(Customs(bot))

import disnake
from disnake.ext import commands
from ui.lobby_views import SetupModeView
from utils import guild_setup, network_retry, custom_invite, ui_theme

class Customs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name="custom", description="Создать кастомную игру Valorant")
    async def create_custom(self, inter: disnake.ApplicationCommandInteraction):
        await network_retry.retry_on_network(lambda: inter.response.defer())

        category, invite_channel, customs_channel = await guild_setup.get_or_create_hub(inter.guild)

        # Роль по имени или по ID (на случай другого написания на сервере)
        role = disnake.utils.get(inter.guild.roles, name="Valorant") or inter.guild.get_role(1474962323021234308)
        ping_line = f"\nПинг: {role.mention}" if role else ""

        invite_text = (
            f"🚀 **{inter.author.display_name}** собирает кастомку!\n"
            f"Переходите в {inter.channel.mention}, чтобы нажать кнопку участия.{ping_line}"
        )
        invite_msg = await invite_channel.send(invite_text)
        custom_invite.register(inter.author.id, invite_channel.id, invite_msg.id)

        embed = ui_theme.brand_embed(
            title="🎮  Настройка Valorant Custom",
            description=(
                f"Категория матча: **{category.name}**\n"
                f"Создавать кастомки: {customs_channel.mention} (роль Valorant).\n"
                f"{ui_theme.DIVIDER}\n"
                f"**RANDOM** — дашборд: команды, карта, агенты → START\n"
                f"**VOTED** — драфт (в разработке)\n\n"
                f"После матча хост жмёт `/finish` · ранг в лобби — `/link`"
            ),
            color=disnake.Color.red(),
        )
        
        view = SetupModeView()
        await inter.edit_original_response(embed=embed, view=view)

def setup(bot):
    bot.add_cog(Customs(bot))

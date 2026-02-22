import disnake
from disnake.ext import commands
from ui.lobby_views import SetupModeView

class Customs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name="custom", description="Создать кастомную игру Valorant")
    async def create_custom(self, inter: disnake.ApplicationCommandInteraction):
        # 1. Моментально отвечаем Дискорду "Я думаю...", чтобы избежать ошибки 3-х секунд
        await inter.response.defer()

        # Создаем красивый Embed
        embed = disnake.Embed(
            title="🎮 Настройка Valorant Custom",
            description=(
                "Вызвавший эту команду становится **Хостом**.\n"
                "Выберите режим формирования команд и пика:"
            ),
            color=disnake.Color.red()
        )
        embed.add_field(name="🎲 RANDOM", value="Быстрый старт, полная случайность.", inline=False)
        embed.add_field(name="🏆 VOTED", value="Выбор капитанов, баны карт и пресеты ролей.", inline=False)

        # Вызываем кнопки из нашего UI файла
        view = SetupModeView()

        # 2. Отправляем итоговое сообщение (редактируем наше "отложенное" сообщение)
        await inter.edit_original_response(embed=embed, view=view)

# Эта функция обязательна, чтобы main.py смог подгрузить этот файл
def setup(bot):
    bot.add_cog(Customs(bot))

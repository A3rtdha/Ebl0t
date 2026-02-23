import disnake
from disnake.ext import commands
import sys, time


class Debug(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()

    @commands.slash_command(name="ping", description="Проверка связи с ботом")
    async def ping(self, inter: disnake.ApplicationCommandInteraction):
        ms = round(self.bot.latency * 1000)
        up = int(time.time() - self.start_time)
        h, m, s = up // 3600, (up % 3600) // 60, up % 60

        deps = {}
        for pkg in ["aiohttp", "easyocr", "cv2", "numpy"]:
            try:
                __import__(pkg)
                deps[pkg] = "✅"
            except ImportError:
                deps[pkg] = "❌ нет"

        embed = disnake.Embed(title="🏓 Pong!", color=disnake.Color.green())
        embed.add_field(name="Latency", value=f"{ms}ms", inline=True)
        embed.add_field(name="Uptime",  value=f"{h:02d}:{m:02d}:{s:02d}", inline=True)
        embed.add_field(name="Python",  value=sys.version.split()[0], inline=True)
        embed.add_field(name="Зависимости", value="\n".join(f"`{k}`: {v}" for k,v in deps.items()), inline=False)
        await inter.response.send_message(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Debug(bot))

import os
import disnake
import logging
import traceback
from disnake.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logging.getLogger("disnake").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

logger = logging.getLogger("Bot")

TOKEN = os.getenv('DISCORD_TOKEN')

intents = disnake.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True

# Прокси: задай PROXY=http://... в .env если нужен, иначе оставь пустым
PROXY = os.getenv('PROXY', '').strip() or None

bot = commands.InteractionBot(
    intents=intents,
    proxy=PROXY,
)


@bot.event
async def on_ready():
    logger.info(f'✅ Бот {bot.user} запущен! Серверов: {len(bot.guilds)}')
    if PROXY:
        logger.info(f'🔀 Прокси: {PROXY}')


def _is_network_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in ("ClientConnectorError", "ClientError", "ServerDisconnectedError", "ConnectionError", "OSError"):
        return True
    if "aiohttp" in type(exc).__module__ and "Client" in name:
        return True
    return False


@bot.event
async def on_slash_command_error(inter: disnake.ApplicationCommandInteraction, error):
    # CommandInvokeError оборачивает реальную ошибку — раскрываем
    original = getattr(error, 'original', error)

    logger.error(
        f"❌ Ошибка /{inter.application_command.name} "
        f"от {inter.author} ({inter.author.id}): "
        f"{type(original).__name__}: {original}"
    )
    traceback.print_exception(type(original), original, original.__traceback__)

    if _is_network_error(original):
        msg = "❌ Не удалось связаться с Discord (обрыв соединения). Проверь интернет/VPN и попробуй через минуту."
    else:
        msg = f"❌ Ошибка: `{type(original).__name__}: {original}`"
    try:
        if not inter.response.is_done():
            await inter.response.send_message(msg, ephemeral=True)
        else:
            await inter.followup.send(msg, ephemeral=True)
    except Exception:
        pass


@bot.event
async def on_error(event_method: str, *args, **kwargs):
    logger.error(f"Необработанное исключение в {event_method}:")
    traceback.print_exc()


def load_cogs():
    cogs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cogs')
    for filename in sorted(os.listdir(cogs_dir)):
        if filename.endswith('.py') and filename != '__init__.py':
            try:
                bot.load_extension(f'cogs.{filename[:-3]}')
                logger.info(f'📦 {filename} загружен')
            except Exception:
                logger.error(f'❌ Ошибка загрузки {filename}:')
                traceback.print_exc()


if __name__ == '__main__':
    if not TOKEN:
        logger.critical("DISCORD_TOKEN не задан в .env!")
        exit(1)

    load_cogs()
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.critical(f"Не удалось запустить: {e}")

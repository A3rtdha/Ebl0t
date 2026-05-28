import atexit
import os
import disnake
import logging
import subprocess
import traceback
from pathlib import Path
from disnake.ext import commands
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / ".eblot.pid"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _stop_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
    else:
        import signal
        os.kill(pid, signal.SIGTERM)


def _ensure_single_instance() -> None:
    if not PID_FILE.exists():
        return
    try:
        old_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        PID_FILE.unlink(missing_ok=True)
        return
    if old_pid != os.getpid() and _pid_alive(old_pid):
        logger.warning("Останавливаю предыдущий инстанс Eblot (PID %s)...", old_pid)
        _stop_pid(old_pid)
    PID_FILE.unlink(missing_ok=True)


def _write_pid_file() -> None:
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    def _cleanup() -> None:
        try:
            if PID_FILE.exists() and int(PID_FILE.read_text(encoding="utf-8")) == os.getpid():
                PID_FILE.unlink()
        except (ValueError, OSError):
            pass

    atexit.register(_cleanup)

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

    _ensure_single_instance()
    _write_pid_file()
    load_cogs()
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.critical(f"Не удалось запустить: {e}")

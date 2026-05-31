import atexit
import logging
import os
import subprocess
import traceback

import disnake
from disnake.ext import commands

from core.config import DISCORD_TOKEN, LOG_LEVEL, PROXY, ROOT
from core.extension_loader import load_extensions
from modules.valorant import setup as valorant_setup
from modules.voice.storage import voice_time

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
            voice_time.flush_active_sessions()
        except Exception:
            pass
        try:
            if PID_FILE.exists() and int(PID_FILE.read_text(encoding="utf-8")) == os.getpid():
                PID_FILE.unlink()
        except (ValueError, OSError):
            pass

    atexit.register(_cleanup)


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("disnake").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

logger = logging.getLogger("Bot")

intents = disnake.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True

bot = commands.InteractionBot(
    intents=intents,
    proxy=PROXY,
)


@bot.event
async def on_ready():
    logger.info("✅ Бот %s запущен! Серверов: %d", bot.user, len(bot.guilds))
    if PROXY:
        logger.info("🔀 Прокси: %s", PROXY)
    await valorant_setup.register(bot)


@bot.event
async def on_guild_join(guild: disnake.Guild):
    await valorant_setup.on_guild_join(guild)


def _is_network_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in ("ClientConnectorError", "ClientError", "ServerDisconnectedError", "ConnectionError", "OSError"):
        return True
    if "aiohttp" in type(exc).__module__ and "Client" in name:
        return True
    return False


@bot.event
async def on_slash_command_error(inter: disnake.ApplicationCommandInteraction, error):
    original = getattr(error, "original", error)

    logger.error(
        "❌ Ошибка /%s от %s (%s): %s: %s",
        inter.application_command.name,
        inter.author,
        inter.author.id,
        type(original).__name__,
        original,
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
    logger.error("Необработанное исключение в %s:", event_method)
    traceback.print_exc()


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.critical("DISCORD_TOKEN не задан в .env!")
        exit(1)

    _ensure_single_instance()
    _write_pid_file()
    load_extensions(bot)
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.critical("Не удалось запустить: %s", e)

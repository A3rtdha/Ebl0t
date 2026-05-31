"""Load bot cogs from modular package paths."""

from __future__ import annotations

import logging
import traceback

log = logging.getLogger("Bot")

EXTENSIONS = [
    "modules.server.cogs.admin_cog",
    "modules.server.cogs.debug_cog",
    "modules.voice.cog.voice_stats_cog",
    "modules.valorant.cogs.customs_cog",
    "modules.valorant.cogs.match_cog",
    "modules.valorant.cogs.profile_cog",
]


def load_extensions(bot) -> None:
    for ext in EXTENSIONS:
        try:
            bot.load_extension(ext)
            log.info("📦 %s загружен", ext)
        except Exception:
            log.error("❌ Ошибка загрузки %s:", ext)
            traceback.print_exc()

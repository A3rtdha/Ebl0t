"""Valorant module bootstrap: persistent views and aftermatch voice channels."""

from __future__ import annotations

import logging

from modules.valorant.services import aftermatch_voices
from modules.valorant.ui.lobby_views import SetupModeView

log = logging.getLogger(__name__)


async def register(bot) -> None:
    bot.add_view(SetupModeView())
    for guild in bot.guilds:
        try:
            await aftermatch_voices.ensure_channels(guild)
        except Exception as e:
            log.warning("Aftermatch-каналы на %s: %s", guild.name, e)


async def on_guild_join(guild) -> None:
    try:
        await aftermatch_voices.ensure_channels(guild)
    except Exception as e:
        log.warning("Aftermatch-каналы на новом сервере %s: %s", guild.name, e)

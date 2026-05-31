"""
Пул голосовых каналов после матча.

На каждом сервере — два постоянных aftermatch-канала. Если оба заняты игроками
из недавно завершённых кастомок, создаётся временный канал (удаляется через 10 мин).

«Занят» = в канале есть кто-то из недавних участников другой кастомки.
Случайный человек, зашедший ждать следующую игру, занятость не создаёт.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Iterable

import disnake

from modules.valorant.services import guild_setup

log = logging.getLogger(__name__)

AFTERMATCH_VC_NAMES = ("🔁 Aftermatch 1", "🔁 Aftermatch 2")
RECENT_PLAYER_WINDOW = 20 * 60  # сек — кого считаем «недавно играли»
TEMP_VC_TTL = 10 * 60  # сек — жизнь временного канала

# guild_id -> channel_id -> user_id -> finished_at
_recent_by_channel: dict[int, dict[int, dict[int, float]]] = {}
_temp_delete_tasks: dict[int, asyncio.Task] = {}


def _prune_recent(guild_id: int, channel_id: int, now: float) -> None:
    bucket = _recent_by_channel.get(guild_id, {}).get(channel_id)
    if not bucket:
        return
    stale = [uid for uid, ts in bucket.items() if now - ts > RECENT_PLAYER_WINDOW]
    for uid in stale:
        del bucket[uid]


def _blocking_members(
    channel: disnake.VoiceChannel,
    current_player_ids: set[int],
    now: float,
) -> list[disnake.Member]:
    """Участники канала, которые недавно играли в другой кастомке."""
    guild_id = channel.guild.id
    _prune_recent(guild_id, channel.id, now)
    recent = _recent_by_channel.get(guild_id, {}).get(channel.id, {})
    blocking: list[disnake.Member] = []
    for member in channel.members:
        if member.id in current_player_ids:
            continue
        ts = recent.get(member.id)
        if ts is not None and now - ts < RECENT_PLAYER_WINDOW:
            blocking.append(member)
    return blocking


def _register_players(guild_id: int, channel_id: int, player_ids: Iterable[int], now: float) -> None:
    bucket = _recent_by_channel.setdefault(guild_id, {}).setdefault(channel_id, {})
    for uid in player_ids:
        bucket[uid] = now


async def ensure_channels(guild: disnake.Guild) -> list[disnake.VoiceChannel]:
    """Создаёт/находит два постоянных aftermatch-канала в hub-категории."""
    category, _, _ = await guild_setup.get_or_create_hub(guild)
    channels: list[disnake.VoiceChannel] = []
    for name in AFTERMATCH_VC_NAMES:
        vc = next(
            (c for c in category.channels if isinstance(c, disnake.VoiceChannel) and c.name == name),
            None,
        )
        if vc is None:
            vc = await guild.create_voice_channel(name=name, category=category)
            log.info("Создан aftermatch-канал %s на %s", name, guild.name)
        channels.append(vc)
    return channels


async def _create_temp_channel(
    guild: disnake.Guild,
    category: disnake.CategoryChannel,
    lobby_id: str,
) -> disnake.VoiceChannel:
    name = f"🔁 Лобби #{lobby_id}"
    vc = await guild.create_voice_channel(name=name, category=category)
    _schedule_temp_delete(vc)
    return vc


def _schedule_temp_delete(channel: disnake.VoiceChannel) -> None:
    cid = channel.id
    old = _temp_delete_tasks.pop(cid, None)
    if old and not old.done():
        old.cancel()

    async def _delete_later():
        try:
            await asyncio.sleep(TEMP_VC_TTL)
            ch = channel.guild.get_channel(cid)
            if isinstance(ch, disnake.VoiceChannel):
                await ch.delete(reason="Временный aftermatch-канал (10 мин)")
                log.info("Удалён временный aftermatch %s", cid)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Не удалось удалить временный aftermatch %s: %s", cid, e)
        finally:
            _temp_delete_tasks.pop(cid, None)

    _temp_delete_tasks[cid] = asyncio.create_task(_delete_later())


async def pick_channel(
    guild: disnake.Guild,
    match_data: dict,
    current_player_ids: set[int],
) -> disnake.VoiceChannel:
    """Выбирает aftermatch-канал: постоянный 1 → 2 → временный."""
    category, _, _ = await guild_setup.get_or_create_hub(guild)
    permanent = await ensure_channels(guild)
    now = time.time()
    lobby_id = str(match_data.get("lobby_id", "0000"))

    for vc in permanent:
        if not _blocking_members(vc, current_player_ids, now):
            return vc

    log.info(
        "Aftermatch 1/2 заняты недавними игроками на %s — временный канал #%s",
        guild.name,
        lobby_id,
    )
    return await _create_temp_channel(guild, category, lobby_id)


async def move_players_after_finish(
    guild: disnake.Guild,
    match_data: dict,
    members: list[disnake.Member],
) -> disnake.VoiceChannel | None:
    """Переносит игроков после /finish в подходящий aftermatch-канал."""
    if not members:
        return None

    player_ids = set(match_data.get("team1_ids", []) + match_data.get("team2_ids", []))
    target = await pick_channel(guild, match_data, player_ids)
    now = time.time()
    _register_players(guild.id, target.id, player_ids, now)

    for member in members:
        try:
            await member.move_to(target)
        except Exception:
            pass

    return target

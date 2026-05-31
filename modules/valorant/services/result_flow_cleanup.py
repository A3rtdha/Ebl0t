"""Отслеживание и удаление промежуточных сообщений флоу /finish → итог матча."""

from __future__ import annotations

import logging
from collections import defaultdict

import disnake

log = logging.getLogger(__name__)

# channel_id -> список message_id (промежуточные шаги)
_pending: dict[int, list[int]] = defaultdict(list)


def track(channel_id: int, message: disnake.Message | None) -> None:
    if message is None:
        return
    _pending[channel_id].append(message.id)


def track_id(channel_id: int, message_id: int) -> None:
    _pending[channel_id].append(message_id)


async def delete_message_ids(
    channel: disnake.abc.Messageable,
    message_ids: list[int],
) -> None:
    """Удаляет сообщения по id (игнорирует уже удалённые)."""
    for mid in message_ids:
        if not mid:
            continue
        try:
            msg = await channel.fetch_message(mid)
            await msg.delete()
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
            pass
        except Exception as e:
            log.debug("delete %s: %s", mid, e)


async def cleanup_channel(
    channel: disnake.abc.Messageable,
    *,
    keep_ids: set[int] | None = None,
    extra_ids: list[int] | None = None,
) -> None:
    """Удаляет все отслежённые сообщения канала, кроме keep_ids."""
    ch_id = channel.id
    ids = _pending.pop(ch_id, [])
    if extra_ids:
        ids.extend(extra_ids)
    keep = keep_ids or set()
    await delete_message_ids(channel, [mid for mid in ids if mid not in keep])

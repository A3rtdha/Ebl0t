"""Сообщение «собирает кастомку» в invite-канале — правим или удаляем при старте матча."""

from __future__ import annotations

import logging

import disnake

log = logging.getLogger(__name__)

# host_id -> (channel_id, message_id)
_pending: dict[int, tuple[int, int]] = {}


def register(host_id: int, channel_id: int, message_id: int) -> None:
    _pending[host_id] = (channel_id, message_id)


async def close_for_host(
    guild: disnake.Guild,
    host: disnake.Member | disnake.User,
    *,
    customs_channel: disnake.abc.GuildChannel | None = None,
) -> None:
    """Помечает сбор завершённым (редактирует сообщение в invite-канале)."""
    entry = _pending.pop(host.id, None)
    if not entry:
        return
    ch_id, msg_id = entry
    channel = guild.get_channel(ch_id)
    if not isinstance(channel, disnake.TextChannel):
        return
    try:
        msg = await channel.fetch_message(msg_id)
        customs_ref = customs_channel.mention if customs_channel else "канале кастомок"
        await msg.edit(
            content=(
                f"✅ **{host.display_name}** — кастомка **началась**, сбор окончен.\n"
                f"Играйте в {customs_ref}."
            ),
            suppress_embeds=True,
        )
    except disnake.NotFound:
        pass
    except Exception as e:
        log.warning(f"Не удалось обновить invite-сообщение: {e}")

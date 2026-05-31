"""Анонс сбора в invite-канале — после создания лобби, удаляем при старте матча."""

from __future__ import annotations

import logging

import disnake

from modules.valorant.services import guild_setup
from shared import ui_theme

log = logging.getLogger(__name__)

# host_id -> (channel_id, message_id)
_pending: dict[int, tuple[int, int]] = {}


def lobby_gather_embed(
    host: disnake.Member | disnake.User,
    voice_channel: disnake.VoiceChannel,
    mode: str,
    *,
    dev_mode: bool = False,
) -> disnake.Embed:
    footer = "🔧 DEV · без публичного анонса" if dev_mode else ui_theme.BRAND_FOOTER
    embed = ui_theme.brand_embed(
        title=f"⏳  Сбор игроков · {mode}" + (" · DEV" if dev_mode else ""),
        description=(
            f"**Организатор:** {host.mention}\n"
            f"**Голосовой канал:** {voice_channel.mention}\n"
            f"{ui_theme.DIVIDER}\n"
            f"Заходите в голосовой канал. Когда все в сборе — "
            f"организатор жмёт **«ВСЕ ГОТОВЫ»**."
        ),
        color=disnake.Color.orange() if dev_mode else ui_theme.COLOR_WARN,
    )
    embed.set_footer(text=footer)
    return embed


def register(host_id: int, channel_id: int, message_id: int) -> None:
    _pending[host_id] = (channel_id, message_id)


async def post_gather_announcement(
    guild: disnake.Guild,
    host: disnake.Member,
    voice_channel: disnake.VoiceChannel,
    mode: str,
    *,
    ping_role: disnake.Role | None = None,
) -> None:
    """Публичный анонс в 📢-сбор-на-кастомки (embed, без кнопок)."""
    _, invite_channel, _ = await guild_setup.get_or_create_hub(guild)
    content = ping_role.mention if ping_role else None
    msg = await invite_channel.send(
        content=content,
        embed=lobby_gather_embed(host, voice_channel, mode),
        allowed_mentions=disnake.AllowedMentions(roles=True, users=True),
    )
    register(host.id, invite_channel.id, msg.id)


async def close_for_host(
    guild: disnake.Guild,
    host: disnake.Member | disnake.User,
    *,
    customs_channel: disnake.abc.GuildChannel | None = None,
) -> None:
    """Удаляет анонс сбора — матч начался, пинг больше не нужен."""
    entry = _pending.pop(host.id, None)
    if not entry:
        return
    ch_id, msg_id = entry
    channel = guild.get_channel(ch_id)
    if not isinstance(channel, disnake.TextChannel):
        return
    try:
        msg = await channel.fetch_message(msg_id)
        await msg.delete()
    except disnake.NotFound:
        pass
    except Exception as e:
        log.warning("Не удалось удалить invite-сообщение: %s", e)

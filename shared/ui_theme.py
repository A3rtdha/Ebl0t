"""Общий стиль embed-ов Eblot: цвета, футер, разделитель."""

from __future__ import annotations

import disnake

BRAND_NAME = "Eblot"
BRAND_FOOTER = "Eblot"

BRAND_ICON = "https://media.valorant-api.com/sprays/0a6db78c-43d4-9b5b-9c5a-7c5e1d2f0001/fulltransparenticon.png"

COLOR_PRIMARY = disnake.Color.from_rgb(88, 101, 242)
COLOR_ACCENT = disnake.Color.from_rgb(255, 70, 85)
COLOR_SUCCESS = disnake.Color.from_rgb(45, 200, 145)
COLOR_WARN = disnake.Color.from_rgb(250, 176, 5)
COLOR_DANGER = disnake.Color.from_rgb(237, 66, 69)
COLOR_NEUTRAL = disnake.Color.from_rgb(54, 57, 63)
COLOR_TEAM_A = disnake.Color.from_rgb(74, 144, 226)
COLOR_TEAM_B = disnake.Color.from_rgb(255, 70, 85)

DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def brand_embed(
    title: str | None = None,
    description: str | None = None,
    color: disnake.Color = COLOR_PRIMARY,
    footer: str | None = None,
) -> disnake.Embed:
    """Embed с футером Eblot (или своим через footer=)."""
    embed = disnake.Embed(title=title, description=description, color=color)
    embed.set_footer(text=footer or BRAND_FOOTER)
    return embed

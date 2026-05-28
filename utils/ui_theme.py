"""
ui_theme.py — единый визуальный стиль бота.

Используй brand_embed(...) вместо disnake.Embed(...) для консистентного вида:
цвета, фирменный футер, аккуратные разделители.
"""

from __future__ import annotations

import disnake

# ── Бренд ──────────────────────────────────────────────────────────────
BRAND_NAME = "Eblot"
BRAND_FOOTER = "Eblot · Кастомки Valorant"

# Иконка в футере/авторе (можно заменить на ссылку с эмодзи-сервера)
BRAND_ICON = "https://media.valorant-api.com/sprays/0a6db78c-43d4-9b5b-9c5a-7c5e1d2f0001/fulltransparenticon.png"

# ── Палитра (в стиле Valorant) ─────────────────────────────────────────
COLOR_PRIMARY = disnake.Color.from_rgb(88, 101, 242)    # сборка/инфо (blurple)
COLOR_ACCENT  = disnake.Color.from_rgb(255, 70, 85)     # Valorant red
COLOR_SUCCESS = disnake.Color.from_rgb(45, 200, 145)    # готово/победа
COLOR_WARN    = disnake.Color.from_rgb(250, 176, 5)     # внимание/проверка
COLOR_DANGER  = disnake.Color.from_rgb(237, 66, 69)     # ошибка/отмена
COLOR_NEUTRAL = disnake.Color.from_rgb(54, 57, 63)      # тёмный нейтральный
COLOR_TEAM_A  = disnake.Color.from_rgb(74, 144, 226)    # Атака (синий)
COLOR_TEAM_B  = disnake.Color.from_rgb(255, 70, 85)     # Защита (красный)

# Тонкая разделительная линия для описаний
DIVIDER = "━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def brand_embed(
    title: str | None = None,
    description: str | None = None,
    color: disnake.Color = COLOR_PRIMARY,
    footer: str | None = None,
) -> disnake.Embed:
    """Эмбед в фирменном стиле с футером."""
    embed = disnake.Embed(title=title, description=description, color=color)
    embed.set_footer(text=footer or BRAND_FOOTER)
    return embed


def apply_brand(embed: disnake.Embed, color: disnake.Color | None = None) -> disnake.Embed:
    """Доводит существующий эмбед до фирменного стиля (футер + цвет)."""
    if color is not None:
        embed.color = color
    if not (embed.footer and embed.footer.text):
        embed.set_footer(text=BRAND_FOOTER)
    return embed


def progress_bar(value: int, maximum: int, length: int = 10) -> str:
    """Текстовый прогресс-бар: ▰▰▰▱▱▱▱▱▱▱"""
    if maximum <= 0:
        return "▱" * length
    filled = round(length * max(0, min(value, maximum)) / maximum)
    return "▰" * filled + "▱" * (length - filled)

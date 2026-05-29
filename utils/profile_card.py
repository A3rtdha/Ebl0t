"""PNG-карточка профиля для /profile."""

import io
import math

from PIL import Image, ImageDraw, ImageFont

from utils import elo_engine

BG = (26, 28, 34)
PANEL = (36, 39, 48)
MUTED = (130, 138, 152)
TEXT = (245, 246, 248)
DIVIDER = (56, 60, 72)

RANK_COLORS = {
    "Iron": (154, 154, 154),
    "Bronze": (160, 103, 78),
    "Silver": (187, 194, 200),
    "Gold": (236, 152, 48),
    "Platinum": (89, 169, 184),
    "Diamond": (180, 137, 255),
    "Ascendant": (31, 160, 104),
    "Immortal": (180, 35, 35),
    "Radiant": (255, 253, 153),
    "Unrated": (148, 155, 164),
}

EBLOT_TIER_COLORS: dict[int, tuple[int, int, int]] = {
    0:    (132, 140, 156),
    850:  (84, 150, 220),
    900:  (92, 132, 255),
    950:  (110, 118, 255),
    1000: (132, 105, 255),
    1050: (155, 98, 255),
    1100: (178, 95, 255),
    1150: (198, 95, 255),
    1220: (215, 105, 255),
    1300: (235, 125, 255),
}

PERF_GRADIENT: list[tuple[float, tuple[int, int, int]]] = [
    (0.00, (75, 150, 255)),
    (0.25, (92, 132, 255)),
    (0.50, (122, 110, 255)),
    (0.72, (158, 98, 255)),
    (0.88, (188, 92, 255)),
    (1.00, (220, 105, 255)),
]

STAT_LABEL = {"KD": "KD", "KAD": "KDA", "ACS": "ACS"}

STAT_RANGES = {
    "KD":  (0.35, 1.75),
    "KAD": (0.45, 2.15),
    "ACS": (110.0, 310.0),
}

W, H = 640, 320


def _custom_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "кастомка"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "кастомки"
    return "кастомок"


def _match_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "матч"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "матча"
    return "матчей"


def _rank_color(rank: str) -> tuple[int, int, int]:
    for tier, color in RANK_COLORS.items():
        if rank.startswith(tier):
            return color
    return RANK_COLORS["Unrated"]


def _eblot_color(elo: int) -> tuple[int, int, int]:
    color = EBLOT_TIER_COLORS[0]
    for min_elo in sorted(EBLOT_TIER_COLORS):
        if elo >= min_elo:
            color = EBLOT_TIER_COLORS[min_elo]
    return color


def _lerp_color(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _perf_score(kind: str, value: float) -> float:
    lo, hi = STAT_RANGES[kind]
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _perf_color(score: float) -> tuple[int, int, int]:
    for i in range(len(PERF_GRADIENT) - 1):
        t0, c0 = PERF_GRADIENT[i]
        t1, c1 = PERF_GRADIENT[i + 1]
        if score <= t1:
            if t1 <= t0:
                return c1
            local = (score - t0) / (t1 - t0)
            return _lerp_color(c0, c1, local)
    return PERF_GRADIENT[-1][1]


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if bold:
        paths = (
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        )
    else:
        paths = (
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _fit_font(draw, text: str, max_w: int, start: int, bold: bool = True):
    size = start
    while size >= 14:
        font = _load_font(size, bold=bold)
        if _text_w(draw, text, font) <= max_w:
            return font
        size -= 1
    return _load_font(14, bold=bold)


def _watermark_layer(w: int, h: int, token: str, accent: tuple[int, int, int], score: float) -> Image.Image:
    pad = 48
    big = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    f = _load_font(15, bold=True)
    alpha = int(18 + score * 14)
    tint = _lerp_color((72, 80, 115), accent, 0.45)
    fill = (*tint, alpha)
    chunk = (token + " ") * 14
    row = -pad
    shift = 0
    while row < h + pad:
        d.text((shift - pad, row), chunk, font=f, fill=fill)
        row += 17
        shift += 9
    rotated = big.rotate(-24, resample=Image.Resampling.BICUBIC, center=(big.width // 2, big.height // 2))
    return rotated.crop((pad, pad, pad + w, pad + h))


def _bezier_points(p0, p1, p2, p3, steps: int = 48) -> list[tuple[float, float]]:
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def _draw_vine_branch(
    d: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    vine_rgb: tuple[int, int, int],
    thorn_rgb: tuple[int, int, int],
    vine_alpha: int,
    thorn_alpha: int,
):
    if len(points) < 2:
        return
    int_pts = [(int(x), int(y)) for x, y in points]
    d.line(int_pts, fill=(*vine_rgb, vine_alpha), width=1, joint="curve")

    for i in range(2, len(points) - 2, 4):
        x0, y0 = points[i - 1]
        x1, y1 = points[i + 1]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        x, y = points[i]
        side = 1 if i % 8 == 2 else -1
        th_len = 5 + (i % 3)
        d.line(
            [(x, y), (x + nx * th_len * side, y + ny * th_len * side)],
            fill=(*thorn_rgb, thorn_alpha),
            width=1,
        )
        d.line(
            [(x, y), (x + nx * th_len * 0.45 * -side, y + ny * th_len * 0.45 * -side)],
            fill=(*thorn_rgb, max(8, thorn_alpha - 6)),
            width=1,
        )


def _vine_background_layer(w: int, h: int, tint: tuple[int, int, int]) -> Image.Image:
    """Едва заметные колючие лианы на фоне."""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    vine_rgb = _lerp_color((48, 42, 62), tint, 0.28)
    thorn_rgb = _lerp_color((62, 52, 88), tint, 0.42)

    vines = [
        ((w * -0.05, h + 24), (w * 0.12, h * 0.72), (w * 0.28, h * 0.42), (w * 0.46, h * 0.18), 20, 14),
        ((w * -0.02, h + 10), (w * 0.08, h * 0.55), (w * 0.22, h * 0.28), (w * 0.38, h * 0.05), 16, 11),
        ((w * 1.05, h + 20), (w * 0.88, h * 0.68), (w * 0.72, h * 0.38), (w * 0.58, h * 0.12), 18, 12),
        ((w * 0.52, h + 16), (w * 0.58, h * 0.62), (w * 0.66, h * 0.34), (w * 0.74, h * 0.08), 14, 10),
    ]
    for p0, p1, p2, p3, va, ta in vines:
        pts = _bezier_points(p0, p1, p2, p3)
        _draw_vine_branch(d, pts, vine_rgb, thorn_rgb, va, ta)

    # лёгкие листья-дуги
    leaf_rgb = (*_lerp_color(vine_rgb, tint, 0.2), 12)
    for cx, cy, r in ((w * 0.18, h * 0.52, 18), (w * 0.82, h * 0.48, 16), (w * 0.62, h * 0.22, 12)):
        d.arc((cx - r, cy - r, cx + r, cy + r), 200, 320, fill=leaf_rgb, width=1)

    return layer


def _paste_avatar(base: Image.Image, avatar: Image.Image, x: int, y: int, size: int):
    avatar = avatar.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, size - 1, size - 1), outline=(70, 74, 88, 255), width=2)
    base.paste(avatar, (x, y), mask)
    base.paste(ring, (x, y), ring)


def _draw_stat_card(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    kind: str,
    value: str,
    accent: tuple[int, int, int],
    score: float,
):
    label = STAT_LABEL.get(kind, kind)
    radius = 14
    tab_h = 22
    tab_pad = 14

    f_lbl = _load_font(11, bold=True)
    lbl_w = _text_w(draw, label, f_lbl)
    tab_w = max(46, lbl_w + tab_pad * 2)

    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    hue_panel = _lerp_color((36, 35, 50), accent, 0.18)
    bg_top = _lerp_color((30, 29, 42), hue_panel, 0.45)
    bg_bot = _lerp_color((39, 36, 54), hue_panel, 0.70)
    for py in range(h):
        t = py / max(h - 1, 1)
        col = _lerp_color(bg_top, bg_bot, t)
        cd.line([(0, py), (w, py)], fill=(*col, 255))

    wm = _watermark_layer(w, h, label, accent, score)
    card = Image.alpha_composite(card, wm)
    cd = ImageDraw.Draw(card)

    f_val = _load_font(28, bold=True)
    val_w = _text_w(cd, value, f_val)
    val_x = (w - val_w) // 2
    val_y = h // 2 - 10
    cd.text((val_x + 1, val_y + 2), value, fill=(10, 8, 16, 125), font=f_val)
    cd.text((val_x, val_y), value, fill=(*TEXT, 255), font=f_val)

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    body = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    body.paste(card, mask=mask)
    img.paste(body, (x, y), body)

    cx = x + w // 2
    gap_l, gap_r = cx - tab_w // 2, cx + tab_w // 2
    border_w = 2 if score >= 0.82 else 1

    draw.arc((x, y, x + radius * 2, y + radius * 2), 180, 270, fill=accent, width=border_w)
    draw.line([(x + radius, y), (gap_l, y)], fill=accent, width=border_w)
    draw.line([(gap_r, y), (x + w - radius, y)], fill=accent, width=border_w)
    draw.arc((x + w - radius * 2, y, x + w, y + radius * 2), 270, 0, fill=accent, width=border_w)
    draw.line([(x + w, y + radius), (x + w, y + h - radius)], fill=accent, width=border_w)
    draw.arc((x + w - radius * 2, y + h - radius * 2, x + w, y + h), 0, 90, fill=accent, width=border_w)
    draw.line([(x + w - radius, y + h), (x + radius, y + h)], fill=accent, width=border_w)
    draw.arc((x, y + h - radius * 2, x + radius * 2, y + h), 90, 180, fill=accent, width=border_w)
    draw.line([(x, y + h - radius), (x, y + radius)], fill=accent, width=border_w)

    tab_x1 = cx - tab_w // 2
    tab_y1 = y - tab_h // 2 + 1
    tab_fill = _lerp_color(PANEL, accent, 0.18)
    draw.rounded_rectangle(
        (tab_x1, tab_y1, tab_x1 + tab_w, tab_y1 + tab_h),
        radius=9,
        fill=tab_fill,
        outline=accent,
        width=border_w,
    )
    draw.text((cx - lbl_w // 2, tab_y1 + 5), label, fill=accent, font=f_lbl)


def render_profile_card(
    *,
    display_name: str,
    riot_id: str,
    rank: str,
    custom_elo: int | None,
    custom_games: int,
    stats: dict,
    avatar_bytes: bytes | None = None,
    updated_ts: int = 0,
) -> io.BytesIO:
    del updated_ts

    ranked_color = _rank_color(rank)
    eblot_color = _eblot_color(custom_elo) if custom_elo else None
    accent = eblot_color or ranked_color

    img = Image.new("RGBA", (W, H), (*BG, 255))
    img = Image.alpha_composite(img, _vine_background_layer(W, H, accent))
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, 5, H), fill=(*accent, 255))

    pad_x = 28
    avatar_size = 80
    avatar_x = W - pad_x - avatar_size
    content_w = avatar_x - pad_x - 16

    f_name = _fit_font(draw, display_name, content_w, 26, bold=True)
    f_id = _load_font(15)
    f_section = _load_font(10)
    f_rank = _fit_font(draw, rank, 250, 22, bold=True)

    y = 22
    draw.text((pad_x, y), display_name, fill=TEXT, font=f_name)
    y += 32
    draw.text((pad_x, y), riot_id, fill=MUTED, font=f_id)
    y += 28

    draw.line((pad_x, y, W - pad_x, y), fill=DIVIDER, width=1)
    y += 16

    col2 = pad_x + 290
    draw.text((pad_x, y), "RANKED", fill=ranked_color, font=f_section)
    draw.text((col2, y), "EBLOT", fill=eblot_color if eblot_color else MUTED, font=f_section)
    y += 18
    draw.text((pad_x, y), rank, fill=ranked_color, font=f_rank)

    if custom_elo:
        eblot = elo_engine.custom_elo_to_rank(custom_elo)
        f_eblot = _fit_font(draw, eblot["name"], 280, 22, bold=True)
        draw.text((col2, y), eblot["name"], fill=eblot_color, font=f_eblot)
        y += 28
        draw.text(
            (col2, y),
            f"{custom_elo} ELO · {custom_games} {_custom_word(custom_games)}",
            fill=MUTED,
            font=f_id,
        )
    else:
        draw.text((col2, y), "Калибровка", fill=MUTED, font=f_id)

    stats_y = 208
    draw.line((pad_x, stats_y - 8, W - pad_x, stats_y - 8), fill=DIVIDER, width=1)

    if stats.get("games", 0) > 0:
        n = stats["games"]
        wl = (
            f"{stats['wins']}W / {stats['losses']}L · {stats['winrate']}% WR · "
            f"последние {n} {_match_word(n)}"
        )
        draw.text((pad_x, stats_y), wl, fill=MUTED, font=f_id)

        pill_y = stats_y + 34
        pill_w = 178
        pill_h = 62
        gap = 14
        stat_items = (
            ("KD", str(stats["kd"]), stats["kd"]),
            ("KAD", str(stats["kad"]), stats["kad"]),
            ("ACS", str(int(stats["avg_acs"])), stats["avg_acs"]),
        )
        for i, (kind, text, raw) in enumerate(stat_items):
            score = _perf_score(kind, float(raw))
            color = _perf_color(score)
            _draw_stat_card(
                img, draw, pad_x + i * (pill_w + gap), pill_y, pill_w, pill_h,
                kind, text, color, score,
            )
    else:
        draw.text((pad_x, stats_y), "Нет матчей в истории", fill=MUTED, font=f_id)

    draw.text((W - 52, H - 22), "Eblot", fill=(58, 62, 72), font=f_section)

    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes))
            _paste_avatar(img, av, avatar_x, 22, avatar_size)
        except Exception:
            pass

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    out.seek(0)
    return out

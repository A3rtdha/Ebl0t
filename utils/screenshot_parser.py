"""
screenshot_parser.py — v6: динамическая сетка строк (5v5, 5v4, 6v4…), не фикс. 10 Y.

Зафиксированные баги в v1-v4 и их решения:
─────────────────────────────────────────────────────────────────────────────
BUG 6: D и A обрезались (например, 13→1, 12→2), потому что блок K/D/A динамически
центрируется игрой как единая строка. Жёсткие узкие колонки COL_D_X1 обрезали края.
  fix: Сначала парсим весь блок KDA (X: 615..755) целиком, разделяя по слэшам
  (через re.findall). Если находим 3 числа — используем их. Иначе fallback на старые колонки.

(Все предыдущие фиксы 1-5 сохранены).
"""

from __future__ import annotations

import os
import re
import logging
import numpy as np
from typing import Optional, Dict, List, Tuple

log = logging.getLogger(__name__)

_tesseract_path_checked = False
_tesseract_has_rus = False
_tesseract_has_ara = False


def _ensure_tesseract_path() -> None:
    global _tesseract_path_checked, _tesseract_has_rus, _tesseract_has_ara
    if _tesseract_path_checked:
        return
    _tesseract_path_checked = True
    try:
        import pytesseract
    except ImportError:
        return
    cmd = os.environ.get("TESSERACT_CMD") or os.environ.get("TESSERACT_PATH")
    if cmd and os.path.isfile(cmd):
        pytesseract.pytesseract.tesseract_cmd = cmd
    elif os.name == "nt":
        for c in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.isfile(c):
                pytesseract.pytesseract.tesseract_cmd = c
                break
    try:
        langs = pytesseract.get_languages() or []
        _tesseract_has_rus = "rus" in langs
        _tesseract_has_ara = "ara" in langs
        if not _tesseract_has_rus:
            log.warning("Tesseract: пакет 'rus' не установлен — кириллические ники хуже")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# КООРДИНАТЫ (% от базового 1456×828, масштабируются через _crop_pct)
# ═══════════════════════════════════════════════════════════

# Fallback для 10 строк (5v5, полная сетка) — если авто-детект не сработал
ROW_Y_PCT_FALLBACK: List[float] = [
    279/828, 318/828, 358/828, 397/828, 436/828,
    476/828, 515/828, 555/828, 594/828, 633/828,
]
ROW_HALF_H_PCT_FALLBACK = 17/828

# Область таблицы scoreboard (для поиска строк)
TABLE_Y1_PCT = 0.24
TABLE_Y2_PCT = 0.80  # 10-я строка на коротких скринах (1024×575) у нижнего края
ACS_SCAN_X1 = 0.33
ACS_SCAN_X2 = 0.43
MIN_ROW_GAP_PCT = 0.028

# Nickname: обрезаем до колонки агента (агент режется в _strip_agent_suffix)
COL_NAME_X1 = 248/1456
COL_NAME_X2 = 405/1456

# ACS: чуть шире влево — иначе сотни (158 → 8)
COL_ACS_X1 = 468/1456
COL_ACS_X2 = 630/1456

# Полный блок K/D/A
COL_KDA_X1 = 615/1456
COL_KDA_X2 = 760/1456
COL_KDA_WIDE_X1 = 580/1456
COL_KDA_WIDE_X2 = 780/1456

# Резервные колонки K/D/A (на случай, если блок KDA распарсится некорректно)
COL_K_X1 = 622/1456
COL_K_X2 = 662/1456
COL_D_X1 = 666/1456
COL_D_X2 = 698/1456
COL_A_X1 = 704/1456
COL_A_X2 = 742/1456

# Поиск строки заголовка таблицы (INDIVIDUALLY SORTED / COMBAT SCORE / KDA / ECON)
HEADER_SCAN_Y1 = 0.16
HEADER_SCAN_Y2 = 0.34
HEADER_BAND_H = 0.045

# Счёт матча (подпись DEFEAT/VICTORY) — калибровка 1919×1079
SCORE_LEFT_X1,  SCORE_LEFT_X2  = 0.35, 0.48
SCORE_RIGHT_X1, SCORE_RIGHT_X2 = 0.48, 0.58
SCORE_Y1, SCORE_Y2 = 0.074, 0.150

# Victory/Defeat
LABEL_X1, LABEL_X2 = 0.40, 0.58
LABEL_Y1, LABEL_Y2 = 0.074, 0.150

# Цвет фона строки: красные vs бирюзовые (scoreboard сортируется по ACS, не по команде!)
TEAM_COLOR_X1, TEAM_COLOR_X2 = 0.14, 0.22

ACS_MAX = 999


# ═══════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════

def _crop_pct(img, x1p: float, y1p: float, x2p: float, y2p: float):
    h, w = img.shape[:2]
    x1 = max(0, int(x1p * w))
    y1 = max(0, int(y1p * h))
    x2 = min(w, int(x2p * w))
    y2 = min(h, int(y2p * h))
    if x2 <= x1 or y2 <= y1:
        return img[0:1, 0:1]
    return img[y1:y2, x1:x2]


def _has_cyrillic(s: str) -> bool:
    return bool(re.search(r"[\u0400-\u04FF]", s))


def _has_arabic(s: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF\u0750-\u077F]", s))


# ═══════════════════════════════════════════════════════════
# ПРЕДОБРАБОТКА
# ═══════════════════════════════════════════════════════════

def _preprocess_digit(patch_bgr, scale: int = 5) -> Optional[np.ndarray]:
    import cv2
    if patch_bgr is None or patch_bgr.size == 0:
        return None

    lab = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2LAB)
    gray = lab[:, :, 0]

    kw = max(gray.shape[1], 5)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 3))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
    tophat = cv2.resize(
        tophat, (tophat.shape[1] * scale, tophat.shape[0] * scale),
        interpolation=cv2.INTER_CUBIC,
    )
    _, b = cv2.threshold(tophat, 25, 255, cv2.THRESH_BINARY)
    b = cv2.bitwise_not(b)
    white_ratio = np.sum(b == 255) / max(b.size, 1)
    if white_ratio < 0.03:
        gray_up = cv2.resize(
            gray, (gray.shape[1] * scale, gray.shape[0] * scale),
            interpolation=cv2.INTER_CUBIC,
        )
        _, b = cv2.threshold(gray_up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.sum(b == 255) / max(b.size, 1) > 0.5:
            b = cv2.bitwise_not(b)
    b = cv2.medianBlur(b, 3)
    return b


def _preprocess_name(patch_bgr, scale: int = 4) -> Optional[np.ndarray]:
    import cv2
    if patch_bgr is None or patch_bgr.size == 0:
        return None

    lab = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2LAB)
    gray = lab[:, :, 0]

    kw = max(gray.shape[1] // 4, 15)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 3))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)

    tophat = cv2.resize(
        tophat, (tophat.shape[1] * scale, tophat.shape[0] * scale),
        interpolation=cv2.INTER_CUBIC,
    )
    _, b = cv2.threshold(tophat, 20, 255, cv2.THRESH_BINARY)
    b = cv2.bitwise_not(b)
    b = cv2.medianBlur(b, 3)

    max_trim = min(int(15 * scale), b.shape[1] // 4)
    black_ratio = (b == 0).mean(axis=0)
    trim_end = -1
    for xi in range(max_trim):
        if black_ratio[xi] > 0.8:
            trim_end = xi
        else:
            break
    if trim_end >= 0:
        b = b[:, trim_end + 1:]

    return b


def _preprocess_label(patch_bgr) -> Optional[np.ndarray]:
    import cv2
    if patch_bgr is None or patch_bgr.size == 0:
        return None

    lab = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2LAB)
    gray = lab[:, :, 0]
    gray = cv2.resize(
        gray, (gray.shape[1] * 3, gray.shape[0] * 3),
        interpolation=cv2.INTER_CUBIC,
    )
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    eq = clahe.apply(gray)
    _, b = cv2.threshold(eq, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.sum(b == 255) / b.size < 0.5:
        b = cv2.bitwise_not(b)
    return b


# ═══════════════════════════════════════════════════════════
# OCR
# ═══════════════════════════════════════════════════════════

def _parse_kda_block(patch_bgr) -> Optional[Tuple[int, int, int]]:
    """Попытка распарсить всю строку 'K / D / A' целиком, чтобы избежать обрезания цифр."""
    try:
        import pytesseract
    except ImportError:
        return None
    _ensure_tesseract_path()
    
    # Пробуем на разных скейлах
    for scale in (5, 4):
        proc = _preprocess_digit(patch_bgr, scale=scale)
        if proc is None:
            continue
            
        # Пробуем с жестким whitelist и без него
        for wl in ["-c tessedit_char_whitelist=0123456789/", ""]:
            for psm in (7, 6, 8):
                try:
                    r = pytesseract.image_to_string(
                        proc, lang="eng", config=f"--psm {psm} --oem 3 {wl}"
                    ).strip()
                    if not wl:
                        r = r.replace('l', '1').replace('I', '1').replace('O', '0').replace('|', '1')
                    
                    m = _KDA_SLASH.search(r.replace("l", "1").replace("I", "1").replace("|", "/"))
                    if m:
                        k, d, a = (int(m.group(i)) for i in range(1, 4))
                        if k <= 60 and d <= 40 and a <= 40:
                            return k, d, a

                    nums = [int(n) for n in re.findall(r"\d+", r)]

                    if len(nums) == 3:
                        k, d, a = nums
                        # Минимальный sanity check для Valorant
                        if k <= 60 and d <= 40 and a <= 40:
                            return k, d, a
                except Exception as e:
                    log.debug(f"kda_block psm={psm}: {e}")
    return None


def _ocr_digit(patch_bgr) -> str:
    try:
        import pytesseract
    except ImportError:
        raise RuntimeError("pytesseract не установлен")
    _ensure_tesseract_path()
    proc = _preprocess_digit(patch_bgr)
    if proc is None:
        return ""
    wl = "-c tessedit_char_whitelist=0123456789"
    for psm in (8, 7, 6):
        try:
            r = pytesseract.image_to_string(
                proc, lang="eng", config=f"--psm {psm} --oem 3 {wl}"
            ).strip()
            if r:
                return r
        except Exception as e:
            log.debug(f"ocr_digit psm={psm}: {e}")
    return ""


def _ocr_digit_score(patch_bgr) -> str:
    try:
        import pytesseract
    except ImportError:
        raise RuntimeError("pytesseract не установлен")
    _ensure_tesseract_path()
    proc = _preprocess_digit(patch_bgr)
    if proc is None:
        return ""
    wl = "-c tessedit_char_whitelist=0123456789"
    for psm in (7, 6, 8):
        try:
            r = pytesseract.image_to_string(
                proc, lang="eng", config=f"--psm {psm} --oem 3 {wl}"
            ).strip()
            if r:
                return r
        except Exception as e:
            log.debug(f"ocr_digit_score psm={psm}: {e}")
    return ""


def _ocr_text(patch_bgr_or_proc, lang: str, preprocess_fn=None) -> str:
    try:
        import pytesseract
    except ImportError:
        raise RuntimeError("pytesseract не установлен")
    _ensure_tesseract_path()

    if preprocess_fn is not None:
        proc = preprocess_fn(patch_bgr_or_proc)
    else:
        proc = patch_bgr_or_proc

    if proc is None:
        return ""
    try:
        return pytesseract.image_to_string(
            proc, lang=lang, config="--psm 6 --oem 3"
        ).strip()
    except Exception as e:
        log.debug(f"ocr_text lang={lang}: {e}")
        return ""


def _ocr_nickname(patch_bgr) -> str:
    _ensure_tesseract_path()
    proc = _preprocess_name(patch_bgr)
    if proc is None:
        return ""

    r_eng = _clean_nickname(_ocr_text(proc, "eng"))

    if _tesseract_has_rus:
        lang = "eng+rus+ara" if _tesseract_has_ara else "eng+rus"
        r_mix = _clean_nickname(_ocr_text(proc, lang))
    else:
        r_mix = r_eng

    return _pick_best_nickname(r_eng, r_mix)


def _pick_best_nickname(eng: str, mixed: str) -> str:
    if not eng and not mixed:
        return ""
    if not eng:
        return mixed
    if not mixed:
        return eng
    if eng == mixed:
        return eng
    mix_cyr = _has_cyrillic(mixed)
    eng_cyr = _has_cyrillic(eng)
    if mix_cyr and not eng_cyr:
        return mixed
    if eng_cyr and not mix_cyr:
        return eng
    return mixed if len(mixed.replace(" ", "")) >= len(eng.replace(" ", "")) else eng


# ═══════════════════════════════════════════════════════════
# ОЧИСТКА И ПАРСИНГ
# ═══════════════════════════════════════════════════════════

_NICK_GARBAGE_LEAD = re.compile(r"^[\s\[\]{}()\\/|#:;'\"!@$%^&*_=+<>?~`\u2022\u00b7\u25cf]+")
_NICK_GARBAGE_TAIL = re.compile(r"[\s\[\]{}()\\/|#:;'\"!@$%^&*_=+<>?~`\u2022\u00b7\u25cf]+$")
_NICK_LEADING_DASH = re.compile(r"^\s*-\s*")
_NICK_TRAIL_COMMA_GARBAGE = re.compile(r"\s*,\s*(,\s*)*.?\s*$")
_NICK_LEADING_CYR_ARTIFACT = re.compile(r"^\s*[ъь]\s+")
_LAT_SUBS = [
    (re.compile(r"^[lI|](?=\d)"), "1"),
    (re.compile(r"\|"), "l"),
]

_AGENT_NAMES = (
    "SOVA", "BRIMSTONE", "PHOENIX", "VIPER", "JETT", "KILLJOY", "CYPHER", "YORU",
    "RAZE", "SAGE", "REYNA", "BREACH", "OMEN", "SKYE", "NEON", "FADE", "HARBOR",
    "GEKKO", "DEADLOCK", "ISO", "CLOVE", "VYSE", "TEJO", "WAYLAY",
)
_AGENT_SUFFIX = re.compile(
    rf"[\s|·•\-–—]*({'|'.join(_AGENT_NAMES)})\s*$",
    re.IGNORECASE,
)
_AGENT_GLUED = re.compile(
    rf"({'|'.join(_AGENT_NAMES)})$",
    re.IGNORECASE,
)
_AGENT_ONLY = {a.upper() for a in _AGENT_NAMES}
_KDA_SLASH = re.compile(r"(\d{1,2})\s*[/\\|lI]\s*(\d{1,2})\s*[/\\|lI]\s*(\d{1,2})")


def _strip_agent_suffix(nick: str) -> str:
    if not nick:
        return nick
    prev = None
    while prev != nick:
        prev = nick
        nick = _AGENT_SUFFIX.sub("", nick).strip()
        nick = _AGENT_GLUED.sub("", nick).strip()
    return nick


def _clean_nickname(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[^\x20-\x7E\u0400-\u04FF\u0600-\u06FF\u0750-\u077F]", "", text)
    text = text.replace("&", "").replace("'", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = _NICK_LEADING_DASH.sub("", text)
    text = _NICK_LEADING_CYR_ARTIFACT.sub("", text).strip()
    text = _NICK_GARBAGE_LEAD.sub("", text).strip()
    text = _NICK_GARBAGE_TAIL.sub("", text).strip()
    text = _NICK_TRAIL_COMMA_GARBAGE.sub("", text).strip()
    if not _has_cyrillic(text):
        for pat, repl in _LAT_SUBS:
            text = pat.sub(repl, text, count=1)
    return _strip_agent_suffix(text)


def _parse_number(text: str, fallback: int = 0) -> int:
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return fallback
    try:
        return int(digits)
    except ValueError:
        return fallback


def _parse_score_single(text: str) -> Optional[int]:
    nums = [int(n) for n in re.findall(r"\d+", text) if int(n) <= 25]
    return nums[0] if nums else None


def _parse_match_scores(img) -> Tuple[Optional[int], Optional[int]]:
    """Сканирует несколько зон подписи счёта (13 VICTORY 7)."""
    found: List[Tuple[float, int]] = []
    for y1, y2 in ((0.05, 0.14), (0.06, 0.15), (0.07, 0.16)):
        for x1, x2 in (
            (0.28, 0.42), (0.32, 0.46), (0.35, 0.48),
            (0.48, 0.58), (0.50, 0.62), (0.55, 0.65),
        ):
            t = _ocr_digit_score(_crop_pct(img, x1, y1, x2, y2))
            for n in re.findall(r"\d+", t):
                v = int(n)
                if 0 < v <= 25:
                    found.append(((x1 + x2) / 2, v))

    if not found:
        return None, None

    found.sort(key=lambda p: p[0])
    uniq: List[Tuple[float, int]] = []
    for x, v in found:
        if not uniq or abs(x - uniq[-1][0]) > 0.06 or v != uniq[-1][1]:
            uniq.append((x, v))

    if len(uniq) >= 2:
        return uniq[0][1], uniq[-1][1]
    if len(uniq) == 1:
        return uniq[0][1], None
    return None, None


def _parse_victory_label(text: str) -> Optional[bool]:
    if not text:
        return None
    t = text.lower()
    if any(w in t for w in ("victory", "win", "побед", "выигр")):
        return True
    if any(w in t for w in ("defeat", "loss", "lose", "пораж", "проигр")):
        return False
    for raw_word in re.split(r"[\s\W]+", t):
        word = re.sub(r"[^a-z]", "", raw_word)
        if len(word) < 4:
            continue
        if _levenshtein_ratio(word, "victory") >= 0.75:
            return True
        if _levenshtein_ratio(word, "defeat") >= 0.75:
            return False
    return None


_OCR_D_FIX: Dict[int, int] = {60: 16, 68: 18, 80: 18, 66: 16, 88: 18, 63: 13, 65: 15, 35: 15, 87: 15}
_OCR_A_FIX: Dict[int, int] = {40: 14, 60: 16, 48: 18, 80: 18}


def _sanitize_kda_acs(k: int, d: int, a: int, acs: int) -> Tuple[int, int, int, int]:
    if acs > ACS_MAX:
        acs = acs % 1000
    if acs > ACS_MAX:
        acs = 0
    if acs < 15 and acs > 0:
        acs2 = acs + 100
        if acs2 <= ACS_MAX:
            acs = acs2
    d = _OCR_D_FIX.get(d, d)
    a = _OCR_A_FIX.get(a, a)
    if 30 <= d <= 39:
        d = d - 20
    if a >= 20 and a % 10 == 0 and a <= 40:
        a = a // 10
    if d > 25 and d >= 100:
        d = min(d % 100, 35)
    k = min(k, 60)
    d = min(d, 35)
    a = min(a, 30)
    return k, d, a, acs


def _nick_is_agent_only(nick: str) -> bool:
    clean = re.sub(r"[^A-Za-z]", "", _strip_agent_suffix(_clean_nickname(nick))).upper()
    return bool(clean) and clean in _AGENT_ONLY


def _is_valid_player_row(nick: str, k: int, d: int, a: int, acs: int) -> bool:
    if _is_header_row(nick) or _nick_is_agent_only(nick):
        return False
    if k == 0 and d == 0 and a == 0 and acs < 50:
        return False
    clean = _strip_agent_suffix(_clean_nickname(nick))
    if len(clean) < 2 and acs < 40:
        return False
    return True


def _is_header_row(nick: str) -> bool:
    u = (nick or "").upper()
    return (
        "SORTED" in u
        or "COMBAT" in u
        or "SCOREBOARD" in u
        or "INDIVIDUALLY" in u
    )


def _row_looks_like_player(img, y_center: float, row_half: float, cols: Optional[Dict] = None) -> bool:
    """Строка игрока: не заголовок, не одно имя агента, есть ACS или KDA."""
    y1p, y2p = y_center - row_half, y_center + row_half
    nx1, nx2 = (cols["name"] if cols and "name" in cols else (COL_NAME_X1, COL_NAME_X2))
    nick = _ocr_nickname(_crop_pct(img, nx1, y1p, nx2, y2p))
    if _is_header_row(nick) or _nick_is_agent_only(nick):
        return False
    acs = _ocr_acs(img, y1p, y2p, cols)
    k, d, a = _parse_row_kda(img, y1p, y2p, cols)
    k, d, a, acs = _sanitize_kda_acs(k, d, a, acs)
    return _is_valid_player_row(nick, k, d, a, acs)


def _detect_columns(img) -> Optional[Dict[str, Tuple[float, float]]]:
    """
    Находит X-границы колонок по строке-заголовку таблицы.

    Сканирует полосы 0.16–0.34 по высоте, читает заголовок через image_to_data,
    ловит слова COMBAT/SCORE/KDA/ECON/SORTED и вычисляет их центры.
    Возвращает {'name','acs','kda'} как (x1,x2) в долях ширины, либо None.
    Так таблица распознаётся при любом разрешении/кропе/новом интерфейсе.
    """
    try:
        import cv2
        import pytesseract
    except ImportError:
        return None
    _ensure_tesseract_path()

    best: Dict[str, float] = {}
    best_hits = 0
    targets = {"SORTED", "COMBAT", "SCORE", "KDA", "ECON", "AVG"}

    y = HEADER_SCAN_Y1
    while y <= HEADER_SCAN_Y2:
        band = _crop_pct(img, 0.10, y, 0.95, y + HEADER_BAND_H)
        if band.size == 0:
            y += 0.02
            continue
        g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (g.shape[1] * 3, g.shape[0] * 3), interpolation=cv2.INTER_CUBIC)
        _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if (b == 255).mean() > 0.5:
            b = cv2.bitwise_not(b)
        try:
            data = pytesseract.image_to_data(
                b, lang="eng", config="--psm 6",
                output_type=pytesseract.Output.DICT,
            )
        except Exception:
            y += 0.02
            continue

        bw = b.shape[1]
        centers: Dict[str, float] = {}
        hits = 0
        for i, raw in enumerate(data["text"]):
            t = re.sub(r"[^A-Z]", "", raw.strip().upper())
            if t not in targets:
                continue
            cx = (data["left"][i] + data["width"][i] / 2) / bw
            full_x = 0.10 + cx * 0.85   # band занимает 0.10..0.95 (ширина 0.85)
            centers[t] = full_x
            hits += 1

        if hits > best_hits:
            best_hits, best = hits, centers
        y += 0.02

    # Нужны хотя бы KDA + одна из колонок ACS/ECON
    if "KDA" not in best or not ({"SCORE", "COMBAT", "AVG", "ECON"} & set(best)):
        return None

    kda_c = best["KDA"]
    acs_parts = [best[k] for k in ("AVG", "COMBAT", "SCORE") if k in best]
    acs_c = sum(acs_parts) / len(acs_parts) if acs_parts else kda_c - 0.09
    econ_c = best.get("ECON", kda_c + 0.08)
    sorted_c = best.get("SORTED", acs_c - 0.11)

    # Границы по серединам между центрами соседних колонок
    acs_x1 = (sorted_c + acs_c) / 2
    acs_x2 = (acs_c + kda_c) / 2
    kda_x1 = (acs_c + kda_c) / 2
    kda_x2 = (kda_c + econ_c) / 2
    name_x1 = max(0.13, sorted_c - 0.11)
    name_x2 = min(sorted_c + 0.03, acs_x1 - 0.01)

    cols = {
        "name": (name_x1, name_x2),
        "acs":  (max(0.0, acs_x1 - 0.01), acs_x2),
        "kda":  (kda_x1, kda_x2),
    }
    log.info(
        f"Колонки по заголовку: name={cols['name']} acs={cols['acs']} kda={cols['kda']}"
    )
    return cols


def _detect_scoreboard_rows(img, cols: Optional[Dict] = None) -> Tuple[List[float], float]:
    """
    Динамически находит Y-центры строк (5v5, 5v4, 6v4 — сетка разная).
    Пики яркости в колонке ACS + фильтр заголовка «INDIVIDUALLY SORTED».
    """
    h, w = img.shape[:2]
    y1, y2 = int(TABLE_Y1_PCT * h), int(TABLE_Y2_PCT * h)
    # Полосу сканирования строк берём из найденной колонки ACS (надёжнее, чем хардкод)
    if cols and "acs" in cols:
        ax1, ax2 = cols["acs"]
        sx1, sx2 = ax1 + 0.005, ax2 - 0.005
        if sx2 - sx1 < 0.04:
            sx1, sx2 = ax1, ax2
    else:
        sx1, sx2 = ACS_SCAN_X1, ACS_SCAN_X2
    x1, x2 = int(sx1 * w), int(sx2 * w)
    patch = img[y1:y2, x1:x2]
    if patch.size == 0:
        return list(ROW_Y_PCT_FALLBACK), ROW_HALF_H_PCT_FALLBACK

    import cv2

    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    kw = max(gray.shape[1] // 2, 12)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 3))
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
    _, bw = cv2.threshold(tophat, 28, 255, cv2.THRESH_BINARY)
    proj = bw.sum(axis=1).astype(float)
    smooth = np.convolve(proj, np.ones(5) / 5, mode="same")
    med = float(np.median(smooth[smooth > 0])) if (smooth > 0).any() else 1.0

    raw_peaks: List[float] = []
    for i in range(1, len(smooth) - 1):
        if smooth[i] > med * 0.45 and smooth[i] >= smooth[i - 1] and smooth[i] >= smooth[i + 1]:
            raw_peaks.append((y1 + i) / h)

    if not raw_peaks:
        log.warning("Строки не найдены по ACS — fallback на фикс. сетку 10")
        return list(ROW_Y_PCT_FALLBACK), ROW_HALF_H_PCT_FALLBACK

    merged = [raw_peaks[0]]
    for p in raw_peaks[1:]:
        if p - merged[-1] >= MIN_ROW_GAP_PCT:
            merged.append(p)

    gaps = [merged[i + 1] - merged[i] for i in range(len(merged) - 1)]
    row_half = (min(gaps) * 0.42) if gaps else ROW_HALF_H_PCT_FALLBACK
    row_half = max(0.014, min(row_half, 0.028))

    centers: List[float] = []
    for cy in merged:
        if _row_looks_like_player(img, cy, row_half, cols):
            centers.append(cy)

    if len(centers) < 2:
        log.warning(f"Мало строк ({len(centers)}) — fallback на фикс. сетку")
        filtered_fb = [
            cy for cy in ROW_Y_PCT_FALLBACK
            if _row_looks_like_player(img, cy, ROW_HALF_H_PCT_FALLBACK, cols)
        ]
        if len(filtered_fb) >= 2:
            return filtered_fb, ROW_HALF_H_PCT_FALLBACK
        return list(ROW_Y_PCT_FALLBACK), ROW_HALF_H_PCT_FALLBACK

    log.info(f"Сетка: {len(centers)} игроков, row_half={row_half:.4f}")
    return centers, row_half


def _row_red_green_delta(img, y1p: float, y2p: float) -> float:
    patch = _crop_pct(img, TEAM_COLOR_X1, y1p, TEAM_COLOR_X2, y2p)
    if patch.size == 0:
        return 0.0
    b, g, r = (float(x) for x in patch.mean(axis=(0, 1)))
    return r - g


def _teams_from_row_colors(img, row_y_pairs: List[Tuple[float, float]]) -> List[str]:
    """
    Scoreboard отсортирован по ACS — команда по цвету строки.
    Два кластера R−G: более «красный» → attack, более «бирюзовый» → defense.
    """
    if not row_y_pairs:
        return []
    deltas = [_row_red_green_delta(img, y1, y2) for y1, y2 in row_y_pairs]
    if len(deltas) == 1:
        return ["attack" if deltas[0] >= 0 else "defense"]
    sorted_d = sorted(deltas)
    mid = sorted_d[len(sorted_d) // 2]
    return ["attack" if d >= mid else "defense" for d in deltas]


def _ocr_acs(img, y1p: float, y2p: float, cols: Optional[Dict] = None) -> int:
    """ACS с повтором, если пропала первая цифра (158→8)."""
    if cols and "acs" in cols:
        ax1, ax2 = cols["acs"]
        candidates = (
            (ax1, ax2),
            (max(0.0, ax1 - 0.015), ax2),
            (max(0.0, ax1 - 0.03), min(1.0, ax2 + 0.01)),
        )
    else:
        candidates = (
            (COL_ACS_X1, COL_ACS_X2),
            (COL_ACS_X1 - 20/1456, COL_ACS_X2),
            (COL_ACS_X1 - 35/1456, COL_ACS_X2 + 10/1456),
        )
    best = 0
    for x1, x2 in candidates:
        val = _parse_number(_ocr_digit(_crop_pct(img, x1, y1p, x2, y2p)))
        if val > best:
            best = val
    return best


def _parse_row_kda(img, y1p: float, y2p: float, cols: Optional[Dict] = None) -> Tuple[int, int, int]:
    if cols and "kda" in cols:
        kx1, kx2 = cols["kda"]
        bands = (
            (kx1, kx2),
            (max(0.0, kx1 - 0.02), min(1.0, kx2 + 0.02)),
            (max(0.0, kx1 - 0.04), min(1.0, kx2 + 0.04)),
        )
    else:
        bands = (
            (COL_KDA_X1, COL_KDA_X2),
            (COL_KDA_WIDE_X1, COL_KDA_WIDE_X2),
            (0.39, 0.53),
        )
    for x1, x2 in bands:
        res = _parse_kda_block(_crop_pct(img, x1, y1p, x2, y2p))
        if res:
            return res

    k = _parse_number(_ocr_digit(_crop_pct(img, COL_K_X1, y1p, COL_K_X2, y2p)))
    d = _parse_number(_ocr_digit(_crop_pct(img, COL_D_X1, y1p, COL_D_X2, y2p)))
    a = _parse_number(_ocr_digit(_crop_pct(img, COL_A_X1, y1p, COL_A_X2, y2p)))
    return k, d, a


# ═══════════════════════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ
# ═══════════════════════════════════════════════════════════

async def parse_screenshot(image_bytes: bytes, content_type: str = "image/png") -> Optional[Dict]:
    try:
        import cv2
    except ImportError:
        raise RuntimeError("OpenCV не установлен: pip install opencv-python-headless")

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        log.error("Не удалось декодировать изображение")
        return None

    h, w = img.shape[:2]
    log.info(f"Скриншот: {w}×{h}px  ratio={w/h:.3f}")

    # ── Счёт ──────────────────────────────────────────────────
    s1 = _parse_score_single(
        _ocr_digit_score(_crop_pct(img, SCORE_LEFT_X1, SCORE_Y1, SCORE_LEFT_X2, SCORE_Y2))
    )
    s2 = _parse_score_single(
        _ocr_digit_score(_crop_pct(img, SCORE_RIGHT_X1, SCORE_Y1, SCORE_RIGHT_X2, SCORE_Y2))
    )
    if s1 is None or s2 is None:
        scan_l, scan_r = _parse_match_scores(img)
        s1 = s1 if s1 is not None else scan_l
        s2 = s2 if s2 is not None else scan_r
    log.info(f"Счёт: {s1} : {s2}")

    # ── Victory/Defeat ────────────────────────────────────
    label_patch = _crop_pct(img, LABEL_X1, LABEL_Y1, LABEL_X2, LABEL_Y2)
    label_proc  = _preprocess_label(label_patch)
    label_lang  = "eng+rus" if _tesseract_has_rus else "eng"
    label_text  = _ocr_text(label_proc, label_lang)
    host_won    = _parse_victory_label(label_text)
    log.info(f"Надпись: '{label_text}' → host_won={host_won}")

    # ── Колонки по заголовку (адаптация под любое разрешение) ──
    cols = _detect_columns(img)
    name_x1, name_x2 = cols["name"] if cols else (COL_NAME_X1, COL_NAME_X2)

    # ── Строки игроков (динамическая сетка) ─────────────────
    row_centers, rh = _detect_scoreboard_rows(img, cols)
    row_boxes = [(cy - rh, cy + rh) for cy in row_centers]
    row_teams = _teams_from_row_colors(img, row_boxes)

    # Минимальное окно OCR — узкая авто-сетка иногда режет цифры/буквы
    rh_ocr = max(rh, 0.020)

    players: List[Dict] = []
    for row_i, (cy, (y1p, y2p), team) in enumerate(
        zip(row_centers, row_boxes, row_teams), start=1
    ):
        oy1, oy2 = cy - rh_ocr, cy + rh_ocr

        riot_id = _ocr_nickname(_crop_pct(img, name_x1, oy1, name_x2, oy2))
        if not riot_id or len(riot_id) < 2:
            # Повтор с расширенным окном имени
            riot_id = _ocr_nickname(
                _crop_pct(img, max(0.0, name_x1 - 0.02), oy1, name_x2 + 0.01, oy2)
            ) or riot_id
        if _is_header_row(riot_id):
            log.debug(f"  Строка {row_i}: заголовок, пропуск")
            continue

        acs = _ocr_acs(img, oy1, oy2, cols)
        k, d, a = _parse_row_kda(img, oy1, oy2, cols)

        _MAX_KDA = 60

        def _retry_digit(col_x1: float, col_x2: float, current: int, name: str) -> int:
            if current >= 10:
                return current
            r = _parse_number(_ocr_digit(
                _crop_pct(img,
                          max(0.0, col_x1 - 8/1456), oy1,
                          min(1.0, col_x2 + 8/1456), oy2)
            ))
            if r > current and r <= _MAX_KDA:
                log.debug(f"  Строка {row_i}: {name} retry {current}→{r}")
                return r
            return current

        if (k == 0 and acs > 80) or (k < 10 and acs > 100):
            k = _retry_digit(COL_K_X1, COL_K_X2, k, "K")
        if d < 10 and (k > 8 or acs > 100):
            d = _retry_digit(COL_D_X1, COL_D_X2, d, "D")
        if a < 10 and (k > 8 or acs > 100):
            a = _retry_digit(COL_A_X1, COL_A_X2, a, "A")
        if d > 25 or (d > k * 4 and k > 0):
            k2, d2, a2 = _parse_row_kda(img, oy1, oy2, cols)
            if d2 <= 25:
                k, d, a = k2, d2, a2

        k, d, a, acs = _sanitize_kda_acs(k, d, a, acs)

        # Строка валидна, если есть осмысленные статы или читаемый ник
        has_stats = acs >= 40 or (k + d + a) > 0
        clean_nick = _strip_agent_suffix(_clean_nickname(riot_id))
        if _nick_is_agent_only(riot_id) or (not has_stats and len(clean_nick) < 3):
            log.debug(f"  Строка {row_i}: мусор/агент, пропуск")
            continue

        # Ник не прочитался, но статы есть — оставляем с плейсхолдером для ручного выбора
        if len(clean_nick) < 2:
            riot_id = f"Игрок {row_i}"

        log.info(f"  Строка {row_i} [{team}] '{riot_id}': K={k} D={d} A={a} ACS={acs}")

        players.append({
            "riot_id":    riot_id,
            "team":       team,
            "kills":      k,
            "deaths":     d,
            "assists":    a,
            "acs":        acs,
            "hs_percent": None,
        })

    if not players:
        log.warning("Не распознан ни один игрок")
        return None

    if s1 is None and s2 is None:
        band = _ocr_digit_score(_crop_pct(img, 0.30, SCORE_Y1, 0.75, SCORE_Y2))
        nums = [int(n) for n in re.findall(r"\d+", band) if int(n) <= 25]
        if len(nums) >= 2:
            s1, s2 = nums[0], nums[1]
        elif len(nums) == 1:
            s1 = nums[0]

    winner_fallback = "attack" if (s1 or 0) > (s2 or 0) else "defense"
    return {
        "host_won":      host_won,
        "winner":        winner_fallback,
        "score_attack":  s1 or 0,
        "score_defense": s2 or 0,
        "players":       players,
    }


# ═══════════════════════════════════════════════════════════
# СОПОСТАВЛЕНИЕ RIOT ID → DISCORD
# ═══════════════════════════════════════════════════════════

def _levenshtein_ratio(s1: str, s2: str) -> float:
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    try:
        from rapidfuzz.distance import Levenshtein
        return Levenshtein.normalized_similarity(s1, s2)
    except ImportError:
        pass
    m, n = len(s1), len(s2)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, n + 1):
            tmp = dp[j]
            dp[j] = prev if s1[i-1] == s2[j-1] else 1 + min(prev, dp[j], dp[j-1])
            prev = tmp
    return 1.0 - dp[n] / max(m, n)


FUZZY_THRESHOLD = 0.75


def match_players_to_discord(
    parsed_players: List[Dict],
    linked_players: Dict[int, Dict],
) -> Dict[int, Dict]:
    if not parsed_players or not linked_players:
        return {}

    exact_full: Dict[str, int] = {}
    exact_name: Dict[str, int] = {}
    name_to_uid: Dict[str, int] = {}

    for uid, entry in linked_players.items():
        name = (entry.get("riot_name") or "").lower().strip()
        tag  = (entry.get("riot_tag")  or "").lower().strip()
        if name:
            exact_name[name] = uid
            name_to_uid[name] = uid
        if name and tag:
            exact_full[f"{name}#{tag}"] = uid

    result: Dict[int, Dict] = {}
    used_uids: set = set()

    def _register(p: Dict, uid: int) -> None:
        if uid not in used_uids:
            used_uids.add(uid)
            result[uid] = {
                "team":       p.get("team"),
                "kills":      p.get("kills",   0) or 0,
                "deaths":     p.get("deaths",  0) or 0,
                "assists":    p.get("assists", 0) or 0,
                "acs":        p.get("acs",     0) or 0,
                "hs_percent": p.get("hs_percent"),
            }

    for p in parsed_players:
        raw = (p.get("riot_id") or "").strip()
        if not raw:
            continue
        low = raw.lower()
        name_part = low.split("#")[0]
        matched: Optional[int] = None

        matched = matched or exact_full.get(low)
        matched = matched or exact_name.get(name_part)

        if matched is None:
            best_r, best_uid = 0.0, None
            for db_name, uid in name_to_uid.items():
                if uid in used_uids:
                    continue
                r = _levenshtein_ratio(name_part, db_name)
                if r > best_r:
                    best_r, best_uid = r, uid
            if best_r >= FUZZY_THRESHOLD:
                log.info(f"Fuzzy '{name_part}' → uid={best_uid} ({best_r:.2f})")
                matched = best_uid

        if matched is not None and matched not in used_uids:
            _register(p, matched)
            log.debug(f"Matched '{raw}' → {matched}")
        else:
            log.debug(f"No match: '{raw}'")

    return result
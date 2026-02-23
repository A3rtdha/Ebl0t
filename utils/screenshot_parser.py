"""
screenshot_parser.py — v5 (validated by pixel-level debugging on 1919×1079 real screenshot)

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

ROW_Y_PCT: List[float] = [
    279/828, 318/828, 358/828, 397/828, 436/828,
    476/828, 515/828, 555/828, 594/828, 633/828,
]
ROW_HALF_H_PCT = 17/828

# Nickname: X1=248 (граница аватарки), X2=480
# Артефакт аватарки срезается автоматически в _preprocess_name()
COL_NAME_X1 = 248/1456
COL_NAME_X2 = 480/1456

COL_ACS_X1 = 483/1456
COL_ACS_X2 = 617/1456

# Полный блок K/D/A для более надежного парсинга
COL_KDA_X1 = 615/1456
COL_KDA_X2 = 755/1456

# Резервные колонки K/D/A (на случай, если блок KDA распарсится некорректно)
COL_K_X1 = 622/1456
COL_K_X2 = 662/1456
COL_D_X1 = 666/1456
COL_D_X2 = 698/1456
COL_A_X1 = 704/1456
COL_A_X2 = 742/1456

# Score: раздельные bbox для левой (атака) и правой (защита) цифры
SCORE_LEFT_X1,  SCORE_LEFT_X2  = 515/1456, 620/1456
SCORE_RIGHT_X1, SCORE_RIGHT_X2 = 830/1456, 930/1456
SCORE_Y1, SCORE_Y2 = 60/828, 115/828

# Victory/Defeat: только центральная надпись (без цифр по краям)
LABEL_X1, LABEL_X2 = 590/1456, 840/1456
LABEL_Y1, LABEL_Y2 = 60/828, 115/828

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
                    
                    # Ищем все непрерывные группы цифр
                    nums = [int(n) for n in re.findall(r'\d+', r)]
                    
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


def _clean_nickname(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[^\x20-\x7E\u0400-\u04FF\u0600-\u06FF\u0750-\u077F]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _NICK_LEADING_DASH.sub("", text)
    text = _NICK_LEADING_CYR_ARTIFACT.sub("", text).strip()
    text = _NICK_GARBAGE_LEAD.sub("", text).strip()
    text = _NICK_GARBAGE_TAIL.sub("", text).strip()
    text = _NICK_TRAIL_COMMA_GARBAGE.sub("", text).strip()
    if not _has_cyrillic(text):
        for pat, repl in _LAT_SUBS:
            text = pat.sub(repl, text, count=1)
    return text


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


_OCR_D_FIX: Dict[int, int] = {60: 16, 68: 18, 80: 18, 66: 16, 88: 18, 63: 13, 65: 15}
_OCR_A_FIX: Dict[int, int] = {40: 14, 60: 16, 48: 18, 80: 18}


def _sanitize_kda_acs(k: int, d: int, a: int, acs: int) -> Tuple[int, int, int, int]:
    if acs > ACS_MAX:
        acs = acs % 1000
    if acs > ACS_MAX:
        acs = 0
    d = _OCR_D_FIX.get(d, d)
    a = _OCR_A_FIX.get(a, a)
    k = min(k, 60)
    d = min(d, 35)
    a = min(a, 30)
    return k, d, a, acs


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
    log.info(f"Счёт: {s1} : {s2}")

    # ── Victory/Defeat ────────────────────────────────────
    label_patch = _crop_pct(img, LABEL_X1, LABEL_Y1, LABEL_X2, LABEL_Y2)
    label_proc  = _preprocess_label(label_patch)
    label_lang  = "eng+rus" if _tesseract_has_rus else "eng"
    label_text  = _ocr_text(label_proc, label_lang)
    host_won    = _parse_victory_label(label_text)
    log.info(f"Надпись: '{label_text}' → host_won={host_won}")

    # ── Строки игроков ────────────────────────────────────
    players: List[Dict] = []
    rh = ROW_HALF_H_PCT

    for i, y_pct in enumerate(ROW_Y_PCT):
        y1p = y_pct - rh
        y2p = y_pct + rh
        team = "attack" if i < 5 else "defense"

        riot_id = _ocr_nickname(_crop_pct(img, COL_NAME_X1, y1p, COL_NAME_X2, y2p))
        if not riot_id or len(riot_id) < 2:
            log.debug(f"  Строка {i+1}: пустой ник, пропуск")
            continue

        acs = _parse_number(_ocr_digit(_crop_pct(img, COL_ACS_X1, y1p, COL_ACS_X2, y2p)))
        
        # Сначала пытаемся распарсить KDA целиком (безопаснее от обрезов)
        kda_patch = _crop_pct(img, COL_KDA_X1, y1p, COL_KDA_X2, y2p)
        kda_res = _parse_kda_block(kda_patch)
        
        if kda_res:
            k, d, a = kda_res
            log.debug(f"  Строка {i+1}: KDA block parsed as {k}/{d}/{a}")
        else:
            # Старый метод жестких колонок с угадыванием (если целый блок провалился)
            k   = _parse_number(_ocr_digit(_crop_pct(img, COL_K_X1,   y1p, COL_K_X2,   y2p)))
            d   = _parse_number(_ocr_digit(_crop_pct(img, COL_D_X1,   y1p, COL_D_X2,   y2p)))
            a   = _parse_number(_ocr_digit(_crop_pct(img, COL_A_X1,   y1p, COL_A_X2,   y2p)))

            _MAX_KDA = 60

            def _retry_digit(col_x1: float, col_x2: float, current: int, name: str) -> int:
                if current >= 10:
                    return current
                r = _parse_number(_ocr_digit(
                    _crop_pct(img,
                              max(0.0, col_x1 - 6/1456), y1p,
                              min(1.0, col_x2 + 6/1456), y2p)
                ))
                if r > current and r <= _MAX_KDA:
                    log.debug(f"  Строка {i+1}: {name} retry {current}→{r}")
                    return r
                return current

            if (k == 0 and acs > 80) or (k < 10 and acs > 200):
                k = _retry_digit(COL_K_X1, COL_K_X2, k, "K")
            if d < 10 and (k > 12 or acs > 200):
                d = _retry_digit(COL_D_X1, COL_D_X2, d, "D")
            if a < 10 and (k > 12 or acs > 200):
                a = _retry_digit(COL_A_X1, COL_A_X2, a, "A")

        k, d, a, acs = _sanitize_kda_acs(k, d, a, acs)
        log.info(f"  Строка {i+1} [{team}] '{riot_id}': K={k} D={d} A={a} ACS={acs}")

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
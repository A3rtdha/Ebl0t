"""
gemini_vision.py — распознавание scoreboard Valorant через Gemini Vision API.

Бесплатный тир Google AI Studio (gemini-2.0-flash):
  • ~15 запросов/мин, 1500/день — для кастомок с запасом.
  • Ключ: https://aistudio.google.com/apikey  →  GEMINI_API_KEY в .env

Возвращает тот же формат, что и screenshot_parser.parse_screenshot():
  {
    "host_won": None,
    "winner": "attack"|"defense"|None,
    "score_attack": int, "score_defense": int,
    "players": [{riot_id, team, kills, deaths, assists, acs, hs_percent}],
    "map": str|None,
  }

Если ключа нет, сети нет или ответ кривой — возвращает None (вызывающий
код откатывается на локальный Tesseract-парсер).
"""

from __future__ import annotations

import os
import json
import base64
import logging
from typing import Optional, Dict, List

log = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# gemini-2.0-flash у части проектов Free tier = limit 0 (429); 2.5-flash обычно работает.
_DEFAULT_MODEL = "gemini-2.5-flash"
_FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash-lite", "gemini-2.0-flash")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
# Прокси для обхода гео-блокировки Gemini в РФ.
# Отдельный GEMINI_PROXY имеет приоритет; иначе используется общий PROXY.
GEMINI_PROXY = (os.getenv("GEMINI_PROXY", "") or os.getenv("PROXY", "")).strip() or None
_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

# Скрин всегда от хоста: зелёные/жёлтая строка = его сторона, красные = враги.
# attack = союзники хоста, defense = враги (см. screenshot_parser.finalize_host_perspective).
_ALLY_ROW_COLORS = frozenset({"green", "yellow", "teal", "lime", "cyan", "ally"})
_ENEMY_ROW_COLORS = frozenset({"red", "enemy"})

_PROMPT = """Ты парсишь скриншот таблицы результатов (scoreboard) матча Valorant.
Скрин сделан игроком (хостом): его тиммейты — зелёный фон строки, сам хост — жёлтый, враги — красный.
Таблица может быть отсортирована по ACS, а не по командам — команду определяй только по цвету строки.

Верни СТРОГО JSON без markdown и пояснений по схеме:
{
  "map": string|null,
  "score": [int, int]|null,           // счёт вверху: [слева, справа] — слева сторона хоста/союзников
  "host_result": "victory"|"defeat"|null,  // надпись VICTORY или DEFEAT у хоста
  "winner_color": "red"|"green"|"yellow"|"teal"|null,  // цвет команды-победителя
  "players": [
    {
      "name": string,
      "agent": string|null,
      "kills": int,
      "deaths": int,
      "assists": int,
      "acs": int,
      "team_color": "red"|"green"|"yellow"|"teal"
    }
  ]
}

Важно:
- Никнеймы — верхняя крупная строка; агент (RAZE, ISO, NEON…) — мелким снизу. В "name" только ник.
- KDA из колонки "K / D / A".
- Победа: 13 раундов у одной стороны; если оба < 13 — победитель с большим числом раундов.
- host_result: VICTORY → "victory", DEFEAT → "defeat".
- team_color строки: red = враг, green или yellow = союзник (жёлтый = сам хост).
- Числа только цифрами. Не выдумывай игроков и статистику.
"""


def is_enabled() -> bool:
    return bool(GEMINI_API_KEY)


def _map_color_to_team(color: Optional[str]) -> str:
    c = (color or "").lower()
    if c in _ENEMY_ROW_COLORS:
        return "defense"
    return "attack"


def _host_won_from_payload(data: dict) -> bool | None:
    hr = (data.get("host_result") or "").lower()
    if hr in ("victory", "win"):
        return True
    if hr in ("defeat", "loss", "lose"):
        return False
    wc = (data.get("winner_color") or "").lower()
    if wc in _ALLY_ROW_COLORS:
        return True
    if wc in _ENEMY_ROW_COLORS:
        return False
    return None


def _coerce_int(v, default: int = 0) -> int:
    try:
        if isinstance(v, bool):
            return default
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return default


def _normalize(data: dict) -> Optional[Dict]:
    raw_players = data.get("players") or []
    if not isinstance(raw_players, list) or not raw_players:
        return None

    players: List[Dict] = []
    for i, p in enumerate(raw_players, start=1):
        if not isinstance(p, dict):
            continue
        name = (p.get("name") or "").strip()
        if not name:
            name = f"Игрок {i}"
        players.append({
            "riot_id":    name,
            "team":       _map_color_to_team(p.get("team_color")),
            "kills":      _coerce_int(p.get("kills")),
            "deaths":     _coerce_int(p.get("deaths")),
            "assists":    _coerce_int(p.get("assists")),
            "acs":        _coerce_int(p.get("acs")),
            "hs_percent": None,
        })

    if not players:
        return None

    # Счёт: [слева (союзники), справа (враги)] на скрине хоста
    score = data.get("score")
    s_attack = s_defense = 0
    if isinstance(score, list) and len(score) == 2:
        s_attack = _coerce_int(score[0])
        s_defense = _coerce_int(score[1])

    host_won = _host_won_from_payload(data)

    return {
        "host_won":      host_won,
        "winner":        "attack",
        "score_attack":  s_attack,
        "score_defense": s_defense,
        "teams_relative_to_host": True,
        "players":       players,
        "map":           (data.get("map") or None),
    }


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    # Срезаем возможные ```json ... ``` обёртки
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Берём первый сбалансированный объект { ... }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _models_to_try() -> tuple[str, ...]:
    """Порядок моделей: из .env первой, затем fallback без дублей."""
    seen: set[str] = set()
    order: list[str] = []
    for m in (GEMINI_MODEL, *_FALLBACK_MODELS):
        if m and m not in seen:
            seen.add(m)
            order.append(m)
    return tuple(order)


async def _call_model(session, model: str, body: dict, params: dict) -> tuple[int, dict | str]:
    import aiohttp
    url = _ENDPOINT.format(model=model)
    async with session.post(
        url, params=params, json=body,
        proxy=GEMINI_PROXY,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status != 200:
            return resp.status, (await resp.text())[:500]
        return 200, await resp.json()


async def parse_scoreboard(image_bytes: bytes, content_type: str = "image/png") -> Optional[Dict]:
    """Распознаёт scoreboard через Gemini. None — если недоступно/ошибка."""
    if not GEMINI_API_KEY:
        return None
    try:
        import aiohttp
    except ImportError:
        log.warning("aiohttp не установлен — Gemini Vision недоступен")
        return None

    mime = content_type if content_type and content_type.startswith("image/") else "image/png"
    b64 = base64.b64encode(image_bytes).decode("ascii")

    body = {
        "contents": [{
            "parts": [
                {"text": _PROMPT},
                {"inline_data": {"mime_type": mime, "data": b64}},
            ]
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    params = {"key": GEMINI_API_KEY}

    payload = None
    used_model = None
    try:
        async with aiohttp.ClientSession() as session:
            for model in _models_to_try():
                try:
                    status, data = await _call_model(session, model, body, params)
                except Exception as e:
                    log.warning(f"Gemini [{model}]: {e}")
                    continue
                if status == 200 and isinstance(data, dict):
                    payload = data
                    used_model = model
                    break
                if status in (400, 403) and isinstance(data, str) and "location" in data.lower():
                    log.warning(
                        "Gemini: гео-блокировка. Задай GEMINI_PROXY в .env — "
                        "иначе Tesseract."
                    )
                    return None
                if status == 429:
                    log.info(f"Gemini [{model}]: квота 429, пробуем другую модель…")
                    continue
                log.warning(f"Gemini [{model}] HTTP {status}: {data[:200] if isinstance(data, str) else data}")
    except Exception as e:
        log.warning(f"Gemini Vision запрос не удался: {e}")
        return None

    if not payload:
        log.warning("Gemini: все модели недоступны (429/ошибка)")
        return None

    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        log.warning("Gemini: неожиданный формат ответа")
        return None

    parsed = _extract_json(text)
    if not parsed:
        log.warning("Gemini: не удалось распарсить JSON из ответа")
        return None

    result = _normalize(parsed)
    if result:
        log.info(
            f"Gemini Vision ({used_model}): {len(result['players'])} игроков, "
            f"счёт {result['score_attack']}:{result['score_defense']}, "
            f"карта={result.get('map')}"
        )
    return result

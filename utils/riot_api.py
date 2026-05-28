"""
Обёртка над Henrik Dev API.
aiohttp импортируется лениво — только при первом реальном запросе,
не при загрузке модуля. Это предотвращает падение бота если пакет
не установлен или используется другое окружение.
"""

import os
import time
import asyncio
import logging

log = logging.getLogger(__name__)

HENRIK_BASE = "https://api.henrikdev.xyz/valorant"
HENRIK_KEY  = os.getenv("HENRIK_API_KEY", "")

# ── Троттлинг запросов к Henrik (бесплатный ключ ≈ 30 req/min) ──────────
# Глобально ограничиваем темп, чтобы не ловить 429.
_MIN_INTERVAL = 2.2          # минимум секунд между запросами
_MAX_CONCURRENCY = 1         # параллельных запросов к API
_rate_lock = asyncio.Lock()
_last_request_ts = 0.0
_semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)


async def _throttle():
    """Гарантирует паузу между запросами к Henrik (анти-rate-limit)."""
    global _last_request_ts
    async with _rate_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _last_request_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_ts = time.monotonic()

RANK_WEIGHTS = {
    "Iron 1": 1,    "Iron 2": 2,    "Iron 3": 3,
    "Bronze 1": 4,  "Bronze 2": 5,  "Bronze 3": 6,
    "Silver 1": 7,  "Silver 2": 8,  "Silver 3": 9,
    "Gold 1": 10,   "Gold 2": 11,   "Gold 3": 12,
    "Platinum 1": 13, "Platinum 2": 14, "Platinum 3": 15,
    "Diamond 1": 16,  "Diamond 2": 17,  "Diamond 3": 18,
    "Ascendant 1": 19, "Ascendant 2": 20, "Ascendant 3": 21,
    "Immortal 1": 22,  "Immortal 2": 23,  "Immortal 3": 24,
    "Radiant": 25,
    "Unrated": 0,
}

RANK_EMOJIS = {
    "Iron": "🩶", "Bronze": "🟫", "Silver": "⬜", "Gold": "🟡",
    "Platinum": "🩵", "Diamond": "💎", "Ascendant": "🟢",
    "Immortal": "🔴", "Radiant": "✨", "Unrated": "❓",
}


def _headers():
    h = {"Content-Type": "application/json"}
    if HENRIK_KEY:
        h["Authorization"] = HENRIK_KEY
    return h


def _parse_mmr_payload(data: dict) -> dict:
    current  = data.get("data", {}).get("current_data", {})
    rank_name = current.get("currenttierpatched", "Unrated") or "Unrated"
    return {
        "rank":   rank_name,
        "rr":     current.get("ranking_in_tier", 0),
        "elo":    current.get("elo", 0),
        "weight": RANK_WEIGHTS.get(rank_name, 0),
    }


async def get_player_rank(name: str, tag: str, region: str = "eu") -> dict | None:
    try:
        import aiohttp
    except ImportError:
        log.warning("aiohttp не установлен — получение ранга недоступно. pip install aiohttp")
        return None

    async with aiohttp.ClientSession() as session:
        return await _fetch_rank(session, name, tag, region)


async def _fetch_rank(session, name: str, tag: str, region: str = "eu",
                      max_retries: int = 2) -> dict | None:
    """
    Один запрос ранга через общий session с троттлингом и обработкой 429.
    Используется и для одиночных вызовов, и для батч-сверки.
    """
    import aiohttp

    url = f"{HENRIK_BASE}/v2/mmr/{region}/{name}/{tag}"
    for attempt in range(max_retries + 1):
        await _throttle()
        try:
            async with _semaphore:
                async with session.get(
                    url, headers=_headers(),
                    timeout=aiohttp.ClientTimeout(total=12),
                ) as resp:
                    if resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", 5) or 5)
                        log.warning(f"Henrik 429 для {name}#{tag} — пауза {retry_after}s")
                        await asyncio.sleep(min(retry_after, 30))
                        continue
                    if resp.status != 200:
                        log.warning(f"Henrik API {resp.status} для {name}#{tag}")
                        return None
                    data = await resp.json()
            return _parse_mmr_payload(data)
        except Exception as e:
            log.error(f"Ошибка Henrik API для {name}#{tag}: {e}")
            if attempt < max_retries:
                await asyncio.sleep(2)
                continue
            return None
    return None


async def refresh_ranks_bulk(
    players: dict[int, dict],
    max_age_sec: int = 6 * 3600,
    on_update=None,
) -> dict[int, dict]:
    """
    Фоновая сверка актуальности рангов для группы игроков.

    • players: {discord_id: db_entry}
    • max_age_sec: пропускаем тех, кого обновляли недавно (экономим лимит API)
    • on_update(discord_id, rank_data): необязательный колбэк после успеха

    Запросы идут последовательно с троттлингом — rate-limit не превышаем.
    Возвращает {discord_id: rank_data} только по обновлённым.
    """
    try:
        import aiohttp
    except ImportError:
        return {}

    now = int(time.time())
    stale = [
        (uid, e) for uid, e in players.items()
        if e.get("riot_name") and e.get("riot_tag")
        and (now - int(e.get("last_updated", 0))) >= max_age_sec
    ]
    if not stale:
        return {}

    log.info(f"Сверка рангов: {len(stale)} игроков (из {len(players)})")
    updated: dict[int, dict] = {}

    async with aiohttp.ClientSession() as session:
        for uid, entry in stale:
            rank_data = await _fetch_rank(
                session, entry["riot_name"], entry["riot_tag"],
                entry.get("region", "eu"),
            )
            if not rank_data:
                continue
            updated[uid] = rank_data
            if on_update:
                try:
                    res = on_update(uid, rank_data)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as e:
                    log.warning(f"on_update callback failed for {uid}: {e}")

    log.info(f"Сверка рангов завершена: обновлено {len(updated)}")
    return updated


async def get_player_puuid(name: str, tag: str) -> str | None:
    try:
        import aiohttp
    except ImportError:
        return None

    url = f"{HENRIK_BASE}/v1/account/{name}/{tag}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_headers(), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        return data.get("data", {}).get("puuid")
    except Exception as e:
        log.error(f"Ошибка PUUID для {name}#{tag}: {e}")
        return None


def rank_to_weight(rank_str: str) -> int:
    return RANK_WEIGHTS.get(rank_str, 0)


def weight_to_rank(weight: int) -> str:
    for rank, w in RANK_WEIGHTS.items():
        if w == weight:
            return rank
    return "Unrated"


def rank_emoji(rank_str: str) -> str:
    tier = rank_str.split(" ")[0] if rank_str else "Unrated"
    return RANK_EMOJIS.get(tier, "❓")

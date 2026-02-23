"""
Обёртка над Henrik Dev API.
aiohttp импортируется лениво — только при первом реальном запросе,
не при загрузке модуля. Это предотвращает падение бота если пакет
не установлен или используется другое окружение.
"""

import os
import logging

log = logging.getLogger(__name__)

HENRIK_BASE = "https://api.henrikdev.xyz/valorant"
HENRIK_KEY  = os.getenv("HENRIK_API_KEY", "")

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


async def get_player_rank(name: str, tag: str, region: str = "eu") -> dict | None:
    try:
        import aiohttp
    except ImportError:
        log.warning("aiohttp не установлен — получение ранга недоступно. pip install aiohttp")
        return None

    url = f"{HENRIK_BASE}/v2/mmr/{region}/{name}/{tag}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_headers(), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    log.warning(f"Henrik API {resp.status} для {name}#{tag}")
                    return None
                data = await resp.json()

        current  = data.get("data", {}).get("current_data", {})
        rank_name = current.get("currenttierpatched", "Unrated")
        rr        = current.get("ranking_in_tier", 0)
        elo       = current.get("elo", 0)

        return {
            "rank":   rank_name,
            "rr":     rr,
            "elo":    elo,
            "weight": RANK_WEIGHTS.get(rank_name, 0),
        }
    except Exception as e:
        log.error(f"Ошибка Henrik API для {name}#{tag}: {e}")
        return None


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

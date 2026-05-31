"""
db_manager.py — хранилище данных бота (JSON).

Структура data.json:
{
  "players": {
    "<discord_id>": {
      "riot_name": str, "riot_tag": str, "region": str,
      "rank": str, "rank_weight": int, "elo": int,
      "custom_elo": int, "custom_games": int,
      "wins": int, "losses": int,
      "last_updated": int,
      "match_history": [          ← история матчей игрока
        {
          "ts": int,              ← unix timestamp
          "result": "win"|"loss",
          "kills": int, "deaths": int, "assists": int,
          "acs": int, "hs_percent": int|null,
          "elo_delta": int,
          "map": str|null
        }
      ]
    }
  }
}
"""

import json
import os
import time
import logging

log = logging.getLogger(__name__)

from core.paths import VALORANT_PROFILE_JSON

DB_PATH = str(VALORANT_PROFILE_JSON)


def _load() -> dict:
    if not os.path.exists(DB_PATH):
        return {"players": {}}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        log.warning("data.json повреждён, создаю заново.")
        return {"players": {}}


def _save(data: dict):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Привязка и обновление ────────────────────────────────────────────

def link_player(discord_id: int, riot_name: str, riot_tag: str, region: str,
                rank: str, rank_weight: int, elo: int):
    data = _load()
    key = str(discord_id)
    existing = data["players"].get(key, {})
    data["players"][key] = {
        "riot_name":     riot_name,
        "riot_tag":      riot_tag,
        "region":        region,
        "rank":          rank,
        "rank_weight":   rank_weight,
        "elo":           elo,
        "custom_elo":    existing.get("custom_elo"),
        "custom_games":  existing.get("custom_games", 0),
        "wins":          existing.get("wins", 0),
        "losses":        existing.get("losses", 0),
        "last_updated":  int(time.time()),
        "match_history": existing.get("match_history", []),
    }
    _save(data)


def get_player(discord_id: int) -> dict | None:
    return _load()["players"].get(str(discord_id))


def get_players_bulk(discord_ids: list) -> dict:
    data = _load()
    return {uid: data["players"][str(uid)] for uid in discord_ids if str(uid) in data["players"]}


def update_rank(discord_id: int, rank: str, rank_weight: int, elo: int):
    data = _load()
    key = str(discord_id)
    if key not in data["players"]:
        return
    data["players"][key].update({
        "rank": rank, "rank_weight": rank_weight,
        "elo": elo, "last_updated": int(time.time()),
    })
    _save(data)


def get_all_players() -> dict:
    return _load().get("players", {})


# ── История матчей ───────────────────────────────────────────────────

def record_match_result(
    winner_ids: list,
    loser_ids: list,
    stats_by_id: dict = None,   # {discord_id: {kills,deaths,assists,acs,hs_percent}}
    elo_changes: dict = None,   # {discord_id: {delta: int}}
    map_name: str = None,
):
    """
    Записывает результат матча в историю каждого игрока.
    Также обновляет счётчики wins/losses.
    """
    data = _load()
    now = int(time.time())
    stats_by_id = stats_by_id or {}
    elo_changes  = elo_changes  or {}

    for uid in winner_ids:
        _append_match(data, uid, "win",  stats_by_id, elo_changes, map_name, now)
    for uid in loser_ids:
        _append_match(data, uid, "loss", stats_by_id, elo_changes, map_name, now)

    _save(data)


def _append_match(data, discord_id, result, stats_by_id, elo_changes, map_name, ts):
    key = str(discord_id)
    if key not in data["players"]:
        data["players"][key] = {
            "riot_name": "", "riot_tag": "", "region": "eu",
            "rank": "Unrated", "rank_weight": 0, "elo": 0,
            "custom_elo": None, "custom_games": 0,
            "wins": 0, "losses": 0,
            "last_updated": ts, "match_history": [],
        }

    p = data["players"][key]
    s = stats_by_id.get(discord_id, {})
    ec = elo_changes.get(discord_id, {})

    entry = {
        "ts":         ts,
        "result":     result,
        "kills":      s.get("kills",   0),
        "deaths":     s.get("deaths",  0),
        "assists":    s.get("assists", 0),
        "acs":        s.get("acs",     0),
        "hs_percent": s.get("hs_percent"),
        "elo_delta":  ec.get("delta",  0),
        "map":        map_name,
    }

    if "match_history" not in p:
        p["match_history"] = []
    p["match_history"].append(entry)

    # Обрезаем историю — храним максимум 100 матчей на игрока
    if len(p["match_history"]) > 100:
        p["match_history"] = p["match_history"][-100:]

    # wins/losses обновляет elo_engine.update_elos_after_match — не дублируем здесь


# ── Статистика ───────────────────────────────────────────────────────

def get_player_stats(discord_id: int, last_n: int = None) -> dict | None:
    """
    Считает агрегированную статистику по матчам игрока.
    last_n — если задан, берёт только последние N матчей.
    """
    player = get_player(discord_id)
    if not player:
        return None

    history = player.get("match_history", [])
    if last_n:
        history = history[-last_n:]

    if not history:
        return {"games": 0}

    games  = len(history)
    wins   = sum(1 for m in history if m["result"] == "win")
    kills  = sum(m.get("kills",   0) for m in history)
    deaths = sum(m.get("deaths",  1) for m in history)
    assists= sum(m.get("assists", 0) for m in history)
    acs_list = [m.get("acs", 0) for m in history if m.get("acs")]

    return {
        "games":    games,
        "wins":     wins,
        "losses":   games - wins,
        "winrate":  round(wins / games * 100) if games else 0,
        "kd":       round(kills / max(deaths, 1), 2),
        "kad":      round((kills + assists) / max(deaths, 1), 2),
        "avg_acs":  round(sum(acs_list) / len(acs_list), 0) if acs_list else 0,
        "history":  history,
    }

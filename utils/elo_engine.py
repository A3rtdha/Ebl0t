"""
elo_engine.py — внутреннее ELO для кастомок.

Система гибридная:
  - Базовое изменение: победа/поражение
  - Бонус/штраф по перформансу: ACS + K/D относительно команды
  - Начальное ELO берётся из ranked-ранга (если привязан) или 1000 (Unrated)

Формула (упрощённый Elo с перформанс-модификатором):
  ΔElo = K * (result - expected) + performance_bonus

  result      = 1.0 за победу, 0.0 за поражение
  expected    = 0.5 (в кастомках не считаем вероятность, у нас нет истории)
  K           = 32 (стандартный коэффициент)
  performance_bonus = от -8 до +8 на основе ACS и K/D
"""

from . import db_manager

# Стартовое ELO по ranked-рангу (если есть)
RANK_TO_START_ELO = {
    0:  1000,   # Unrated
    1:  800,    # Iron 1
    2:  817,    3: 833,
    4:  850,    # Bronze 1
    5:  867,    6: 883,
    7:  900,    # Silver 1
    8:  917,    9: 933,
    10: 950,    # Gold 1
    11: 967,    12: 983,
    13: 1000,   # Platinum 1
    14: 1017,   15: 1033,
    16: 1050,   # Diamond 1
    17: 1067,   18: 1083,
    19: 1100,   # Ascendant 1
    20: 1120,   21: 1140,
    22: 1160,   # Immortal 1
    23: 1190,   24: 1220,
    25: 1300,   # Radiant
}

K = 32
PERF_MAX = 8   # максимальный бонус/штраф за перформанс

DB_PATH = db_manager.DB_PATH

import json, os

def _load():
    if not os.path.exists(DB_PATH):
        return {"players": {}}
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _save(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_custom_elo(discord_id: int) -> int:
    """Возвращает текущее custom ELO игрока. Если нет — инициализирует."""
    data = _load()
    key = str(discord_id)
    player = data["players"].get(key, {})

    if "custom_elo" not in player:
        # Инициализируем из ранга или дефолт 1000
        rank_weight = player.get("rank_weight", 0)
        start = RANK_TO_START_ELO.get(rank_weight, 1000)
        player["custom_elo"] = start
        player["custom_games"] = 0
        data["players"][key] = player
        _save(data)

    return player["custom_elo"]


def _performance_bonus(player_stats: dict, team_stats: list[dict]) -> float:
    """
    Считает бонус перформанса [-PERF_MAX, +PERF_MAX].
    player_stats и team_stats — списки словарей {"acs": int, "kd": float}
    """
    if not team_stats:
        return 0.0

    avg_acs = sum(p.get("acs", 0) for p in team_stats) / len(team_stats)
    avg_kd  = sum(p.get("kd", 1.0) for p in team_stats) / len(team_stats)

    p_acs = player_stats.get("acs", avg_acs)
    p_kd  = player_stats.get("kd", avg_kd)

    # Нормализуем: насколько игрок лучше/хуже среднего по команде
    acs_diff = (p_acs - avg_acs) / max(avg_acs, 1)  # от -1 до +1 примерно
    kd_diff  = (p_kd  - avg_kd)  / max(avg_kd,  0.1)

    # Взвешиваем ACS 60%, K/D 40%
    perf_score = 0.6 * acs_diff + 0.4 * kd_diff

    # Клампируем в [-1, 1], масштабируем в [-PERF_MAX, +PERF_MAX]
    perf_score = max(-1.0, min(1.0, perf_score))
    return round(perf_score * PERF_MAX, 1)


def update_elos_after_match(
    winner_ids: list[int],
    loser_ids: list[int],
    stats_by_id: dict[int, dict] = None,
) -> dict[int, dict]:
    """
    Обновляет ELO всех игроков после матча.
    
    stats_by_id: {discord_id: {"acs": int, "kills": int, "deaths": int, "assists": int}}
                 Если None или игрок отсутствует — перформанс-бонус = 0.
    
    Возвращает словарь {discord_id: {"old": int, "new": int, "delta": int}}.
    """
    if stats_by_id is None:
        stats_by_id = {}

    data = _load()
    changes = {}

    def _kd(s: dict) -> float:
        d = s.get("deaths", 1)
        return s.get("kills", 0) / max(d, 1)

    def _enriched(player_id: int) -> dict:
        s = stats_by_id.get(player_id, {})
        return {"acs": s.get("acs", 0), "kd": _kd(s)}

    winner_stats = [_enriched(uid) for uid in winner_ids]
    loser_stats  = [_enriched(uid) for uid in loser_ids]

    all_players = [(uid, 1.0, winner_stats) for uid in winner_ids] + \
                  [(uid, 0.0, loser_stats)  for uid in loser_ids]

    for uid, result, team_stats in all_players:
        key = str(uid)
        if key not in data["players"]:
            data["players"][key] = {}

        player = data["players"][key]
        old_elo = player.get("custom_elo") or RANK_TO_START_ELO.get(player.get("rank_weight", 0), 1000)

        base_delta = K * (result - 0.5)  # +16 за победу, -16 за поражение
        perf_bonus = _performance_bonus(_enriched(uid), team_stats)
        total_delta = round(base_delta + perf_bonus)

        new_elo = max(100, old_elo + total_delta)  # минимум 100

        player["custom_elo"] = new_elo
        player["custom_games"] = player.get("custom_games", 0) + 1
        if result == 1.0:
            player["wins"] = player.get("wins", 0) + 1
        else:
            player["losses"] = player.get("losses", 0) + 1

        data["players"][key] = player
        changes[uid] = {
            "old": old_elo,
            "new": new_elo,
            "delta": total_delta,
            "perf_bonus": perf_bonus,
        }

    _save(data)
    return changes


def custom_elo_to_rank_label(elo: int) -> str:
    """Переводит custom ELO в читаемую метку."""
    if elo < 850:   return "🩶 Iron"
    if elo < 900:   return "🟫 Bronze"
    if elo < 950:   return "⬜ Silver"
    if elo < 1000:  return "🟡 Gold"
    if elo < 1050:  return "🩵 Platinum"
    if elo < 1100:  return "💎 Diamond"
    if elo < 1150:  return "🟢 Ascendant"
    if elo < 1220:  return "🔴 Immortal"
    return "✨ Custom Radiant"

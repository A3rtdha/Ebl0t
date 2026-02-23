import random
from itertools import combinations
from .game_data import MAP_POOL, AGENT_POOL
from . import db_manager


def get_random_maps(count=3):
    return random.sample(MAP_POOL, count)


def assign_random_agents(players):
    assignments = {}
    for player in players:
        assignments[player] = random.choice(AGENT_POOL)
    return assignments


def get_random_agent():
    """Возвращает одного случайного агента"""
    return random.choice(AGENT_POOL)


# ---------------------------------------------------------------------------
# Балансировка команд по рангу
# ---------------------------------------------------------------------------

def _get_weight(player, db_data: dict) -> int:
    """Получает числовой вес игрока из БД. Если не привязан — 0 (Unrated)."""
    uid = player.id if hasattr(player, "id") else int(player)
    entry = db_data.get(uid)
    return entry["rank_weight"] if entry else 0


def split_teams_balanced(players: list) -> tuple[list, list]:
    """
    Делит игроков на две команды с минимальной разницей суммарного рейтинга.
    
    Алгоритм: перебираем все комбинации (половина игроков в team1),
    выбираем ту, где разница сумм минимальна.
    При большом числе игроков (>12) — жадный алгоритм.
    
    Возвращает (team1, team2) — списки Member-объектов.
    """
    n = len(players)
    if n < 2:
        return players, []

    half = n // 2
    ids = [p.id if hasattr(p, "id") else int(p) for p in players]
    db_data = db_manager.get_players_bulk(ids)

    # Если никто не привязан — обычный рандом
    all_unrated = all(_get_weight(p, db_data) == 0 for p in players)
    if all_unrated:
        shuffled = players.copy()
        random.shuffle(shuffled)
        return shuffled[:half], shuffled[half:]

    weights = [_get_weight(p, db_data) for p in players]
    total = sum(weights)

    best_combo = None
    best_diff = float("inf")

    if n <= 12:
        # Полный перебор
        for combo in combinations(range(n), half):
            s1 = sum(weights[i] for i in combo)
            diff = abs(total - 2 * s1)
            if diff < best_diff:
                best_diff = diff
                best_combo = combo
    else:
        # Жадный: сортируем по убыванию, раскидываем поочерёдно
        sorted_idx = sorted(range(n), key=lambda i: weights[i], reverse=True)
        t1_sum, t2_sum = 0, 0
        t1_idx, t2_idx = [], []
        for idx in sorted_idx:
            if len(t1_idx) < half and (len(t2_idx) >= half or t1_sum <= t2_sum):
                t1_idx.append(idx)
                t1_sum += weights[idx]
            else:
                t2_idx.append(idx)
                t2_sum += weights[idx]
        best_combo = t1_idx

    team1 = [players[i] for i in best_combo]
    team2 = [players[i] for i in range(n) if i not in set(best_combo)]
    return team1, team2


# Старый метод оставляем для совместимости (используется в рандом-режиме без БД)
def split_teams(players):
    return split_teams_balanced(players)


def format_teams_embed_fields(team1: list, team2: list, db_data: dict = None) -> tuple[str, str]:
    """
    Формирует строки для embed-полей команд с указанием рангов.
    Если db_data=None — подтягивает сам.
    """
    if db_data is None:
        ids = [p.id for p in team1 + team2]
        db_data = db_manager.get_players_bulk(ids)

    def fmt_player(p):
        entry = db_data.get(p.id)
        if entry:
            from .riot_api import rank_emoji
            emoji = rank_emoji(entry["rank"])
            return f"{emoji} {p.mention} — {entry['rank']}"
        return f"❓ {p.mention} — не привязан"

    t1_str = "\n".join(fmt_player(p) for p in team1)
    t2_str = "\n".join(fmt_player(p) for p in team2)

    t1_total = sum(_get_weight(p, db_data) for p in team1)
    t2_total = sum(_get_weight(p, db_data) for p in team2)

    t1_str += f"\n\n*Суммарный рейтинг: {t1_total}*"
    t2_str += f"\n\n*Суммарный рейтинг: {t2_total}*"

    return t1_str, t2_str

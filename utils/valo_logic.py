import random
from itertools import combinations
from .game_data import MAP_POOL, AGENT_POOL
from . import db_manager
from .elo_engine import RANK_TO_START_ELO

# ELO для игрока без данных (считаем «средним», чтобы не валить всех в одну команду)
DEFAULT_ELO = 1000
# Сколько кастомок нужно, чтобы полностью доверять Custom ELO вместо ранга
CALIBRATION_GAMES = 10


def get_random_maps(count=3):
    return random.sample(MAP_POOL, count)


def assign_random_agents(players):
    assignments = {}
    for player in players:
        assignments[player] = random.choice(AGENT_POOL)
    return assignments


def get_random_agent(exclude: str | None = None):
    """Случайный агент; exclude — не повторять текущего при реролле."""
    pool = [a for a in AGENT_POOL if a != exclude] if exclude else list(AGENT_POOL)
    return random.choice(pool or AGENT_POOL)


# ---------------------------------------------------------------------------
# Балансировка команд по рангу
# ---------------------------------------------------------------------------

def _player_id(player) -> int:
    return player.id if hasattr(player, "id") else int(player)


def _get_skill(player, db_data: dict) -> float | None:
    """
    Оценка силы игрока в ELO-шкале (~800–1300).

    Логика:
      • не привязан / нет данных          → None (исключаем из расчёта весов);
      • привязан, но мало кастомок         → опираемся на стартовое ELO от ранга;
      • есть Custom ELO                    → плавно смешиваем ранг и Custom ELO
                                             (чем больше игр — тем больше веса у Custom).
    """
    entry = db_data.get(_player_id(player))
    if not entry:
        return None

    rank_start = RANK_TO_START_ELO.get(entry.get("rank_weight", 0), DEFAULT_ELO)
    custom = entry.get("custom_elo")
    games = entry.get("custom_games", 0) or 0

    if custom and games > 0:
        confidence = min(games / CALIBRATION_GAMES, 1.0)
        return round(rank_start * (1 - confidence) + custom * confidence)
    return float(rank_start)


def _get_weight(player, db_data: dict) -> float:
    """Сила игрока для отображения/суммирования (None → среднее ELO)."""
    skill = _get_skill(player, db_data)
    return skill if skill is not None else DEFAULT_ELO


def player_skill_elo(player, db_data: dict) -> int:
    """ELO-сила игрока для баланса и отображения в лобби."""
    return round(_get_weight(player, db_data))


def team_average_skill(team: list, db_data: dict) -> int:
    """Средняя сила команды (ELO-шкала). 0 — если команда пуста."""
    if not team:
        return 0
    return round(sum(_get_weight(p, db_data) for p in team) / len(team))


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

    team_small = n // 2
    team_large = n - team_small
    ids = [_player_id(p) for p in players]
    db_data = db_manager.get_players_bulk(ids)

    skills = [_get_skill(p, db_data) for p in players]

    # Если вообще никто не привязан — обычный рандом
    if all(s is None for s in skills):
        shuffled = players.copy()
        random.shuffle(shuffled)
        return shuffled[:team_small], shuffled[team_small:]

    # Неизвестных считаем «средними», чтобы не сваливать их в одну команду
    weights = [s if s is not None else DEFAULT_ELO for s in skills]

    best_combo = None
    best_diff = float("inf")

    if n <= 12:
        for combo in combinations(range(n), team_small):
            s1 = sum(weights[i] for i in combo)
            diff = abs(sum(weights) - 2 * s1)
            if diff < best_diff:
                best_diff = diff
                best_combo = combo
    else:
        sorted_idx = sorted(range(n), key=lambda i: weights[i], reverse=True)
        t1_sum, t2_sum = 0, 0
        t1_idx, t2_idx = [], []
        for idx in sorted_idx:
            if len(t1_idx) < team_small and (len(t2_idx) >= team_large or t1_sum <= t2_sum):
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

    def _avg(team):
        if not team:
            return 0
        return round(sum(_get_weight(p, db_data) for p in team) / len(team))

    t1_avg, t2_avg = _avg(team1), _avg(team2)

    t1_str += f"\n\n*Средняя сила: {t1_avg}*"
    t2_str += f"\n\n*Средняя сила: {t2_avg}*"

    return t1_str, t2_str

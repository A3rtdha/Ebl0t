import random
from itertools import combinations
from .game_data import MAP_POOL, AGENT_POOL
from . import db_manager
from .elo_engine import RANK_TO_START_ELO

DEFAULT_ELO = 1000
CALIBRATION_GAMES = 10  # после стольких матчей Custom ELO весит больше, чем ranked


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


def _player_id(player) -> int:
    return player.id if hasattr(player, "id") else int(player)


def _get_skill(player, db_data: dict) -> float | None:
    """Сила для баланса: смесь ranked и Custom ELO; без /link — None."""
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


def _combo_split(players: list, weights: list[float], team1_size: int) -> tuple[list, list, float]:
    """team1 = Attack. Возвращает (team1, team2, |разница средних ELO|)."""
    n = len(players)
    if team1_size <= 0:
        return [], list(players), float("inf")
    if team1_size >= n:
        return list(players), [], float("inf")

    best_combo: tuple[int, ...] | None = None
    best_avg_diff = float("inf")

    if n <= 12:
        for combo in combinations(range(n), team1_size):
            idx1 = set(combo)
            w1 = [weights[i] for i in combo]
            w2 = [weights[i] for i in range(n) if i not in idx1]
            avg1 = sum(w1) / len(w1) if w1 else 0
            avg2 = sum(w2) / len(w2) if w2 else 0
            avg_diff = abs(avg1 - avg2)
            if avg_diff < best_avg_diff:
                best_avg_diff = avg_diff
                best_combo = combo
    else:
        team2_size = n - team1_size
        sorted_idx = sorted(range(n), key=lambda i: weights[i], reverse=True)
        t1_idx, t2_idx = [], []
        t1_sum, t2_sum = 0.0, 0.0
        for idx in sorted_idx:
            if len(t1_idx) < team1_size and (
                len(t2_idx) >= team2_size or t1_sum <= t2_sum
            ):
                t1_idx.append(idx)
                t1_sum += weights[idx]
            else:
                t2_idx.append(idx)
                t2_sum += weights[idx]
        best_combo = tuple(t1_idx)
        if t1_idx and t2_idx:
            best_avg_diff = abs(t1_sum / len(t1_idx) - t2_sum / len(t2_idx))

    if best_combo is None:
        shuffled = players.copy()
        random.shuffle(shuffled)
        t1 = shuffled[:team1_size]
        t2 = shuffled[team1_size:]
        return t1, t2, float("inf")

    team1 = [players[i] for i in best_combo]
    team2 = [players[i] for i in range(n) if i not in set(best_combo)]
    return team1, team2, best_avg_diff


def roster_imbalance_note(team1: list, team2: list) -> str | None:
    """Подсказка при 5v4 и т.п."""
    d = abs(len(team1) - len(team2))
    if d == 0:
        return None
    big, small = (team1, team2) if len(team1) > len(team2) else (team2, team1)
    side = "Атака" if big is team1 else "Защита"
    return f"Состав **{len(team1)}v{len(team2)}** · лишний в **{side}** (подобран по ELO)"


def split_teams_balanced(players: list) -> tuple[list, list]:
    """
    Делит на Attack (team1) и Defense (team2).
    При нечётном числе перебирает, с какой стороны лишний игрок — выбирает вариант с ближайшими средними ELO.
    """
    n = len(players)
    if n == 0:
        return [], []
    if n == 1:
        return players, []

    small = n // 2
    large = n - small
    ids = [_player_id(p) for p in players]
    db_data = db_manager.get_players_bulk(ids)
    skills = [_get_skill(p, db_data) for p in players]

    if all(s is None for s in skills):
        shuffled = players.copy()
        random.shuffle(shuffled)
        return shuffled[:small], shuffled[large:]

    weights = [s if s is not None else DEFAULT_ELO for s in skills]

    if small == large:
        team1, team2, _ = _combo_split(players, weights, small)
        return team1, team2

    t1a, t2a, diff_a = _combo_split(players, weights, small)
    t1b, t2b, diff_b = _combo_split(players, weights, large)
    if diff_a <= diff_b:
        return t1a, t2a
    return t1b, t2b


def split_teams(players):
    return split_teams_balanced(players)


def team_balance_grade(team1: list, team2: list, db_data: dict | None = None) -> tuple[str, int]:
    """Оценка баланса split: (метка, балл 0–100) по разнице средних ELO команд."""
    if not team1 and not team2:
        return "—", 0
    if db_data is None:
        ids = [_player_id(p) for p in team1 + team2]
        db_data = db_manager.get_players_bulk(ids)
    avg1 = team_average_skill(team1, db_data) if team1 else 0
    avg2 = team_average_skill(team2, db_data) if team2 else 0
    diff = abs(avg1 - avg2)
    score = max(0, min(100, 100 - diff // 2))
    roster_gap = abs(len(team1) - len(team2))
    if roster_gap == 1:
        score = max(0, score - 8)
    elif roster_gap > 1:
        score = max(0, score - 15)
    if score >= 90:
        label = "Отличный"
    elif score >= 75:
        label = "Хороший"
    elif score >= 55:
        label = "Нормальный"
    else:
        label = "Плохой"
    return label, score

"""
elo_engine.py — продвинутая гибридная система ELO для кастомок.

Особенности системы:
1. Вычисление вероятности победы (ожидаемый исход на основе разницы ELO команд).
2. Margin of Victory (MoV) — учет разницы в счете (13:12 дает меньше ELO, чем 13:0).
3. Z-Score Performance (CPI) — оценка импакта игрока относительно всего лобби (ACS + K/D).
4. Динамический K-Factor — быстрый рост для новичков, стабильность для ветеранов.
"""

import math
from . import db_manager
import json, os

RANK_TO_START_ELO = {
    0:  1000, 1:  800,  2:  817,  3: 833, 4:  850,  5:  867,  6: 883,
    7:  900,  8:  917,  9: 933, 10: 950,  11: 967, 12: 983, 13: 1000,
    14: 1017, 15: 1033, 16: 1050, 17: 1067, 18: 1083, 19: 1100, 20: 1120,
    21: 1140, 22: 1160, 23: 1190, 24: 1220, 25: 1300,
}

DB_PATH = db_manager.DB_PATH

def _load():
    if not os.path.exists(DB_PATH): return {"players": {}}
    with open(DB_PATH, "r", encoding="utf-8") as f: return json.load(f)

def _save(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_custom_elo(discord_id: int) -> int:
    data = _load()
    player = data["players"].get(str(discord_id), {})
    if "custom_elo" not in player:
        start = RANK_TO_START_ELO.get(player.get("rank_weight", 0), 1000)
        return start
    return player["custom_elo"]

# ==========================================
# ЯДРО МАТЕМАТИКИ СИСТЕМЫ
# ==========================================

def _get_k_factor(games_played: int) -> int:
    """Динамическая волатильность: новички калибруются быстрее."""
    if games_played < 10: return 50
    if games_played < 25: return 35
    return 20

def _get_mov_multiplier(score_winner: int, score_loser: int) -> float:
    """Множитель разницы раундов. 13:12 = 0.57x | 13:6 = 0.93x | 13:0 = 1.30x"""
    if score_winner is None or score_loser is None:
        return 1.0  # Если счет не указан (ввели вручную без счета)

    diff = abs(score_winner - score_loser)
    # Формула, гасящая потные катки и бустящая разгромы
    return 0.5 + (min(diff, 13) / 13.0) * 0.8

def _calculate_team_elo(team_ids: list, data: dict) -> float:
    """Считает среднее ELO команды."""
    if not team_ids: return 1000.0
    total = 0
    for uid in team_ids:
        p = data["players"].get(str(uid), {})
        total += p.get("custom_elo") or RANK_TO_START_ELO.get(p.get("rank_weight", 0), 1000)
    return total / len(team_ids)

def _calculate_performance_multipliers(stats_by_id: dict, all_ids: list) -> dict:
    """
    Вычисляет множитель перформанса (P_M) для каждого игрока через Z-Score лобби.
    Возвращает: {discord_id: float (от 0.5 до 1.5)}
    """
    multipliers = {uid: 1.0 for uid in all_ids}
    if not stats_by_id: return multipliers

    # Собираем данные лобби
    acs_list, kd_list = [], []
    for uid in all_ids:
        s = stats_by_id.get(uid, {})
        acs = s.get("acs", 0)
        d = max(s.get("deaths", 1), 1)
        kd = s.get("kills", 0) / d
        acs_list.append(acs)
        kd_list.append(kd)

    if not acs_list: return multipliers

    avg_acs = sum(acs_list) / len(acs_list)
    avg_kd = sum(kd_list) / len(kd_list)

    # Стандартное отклонение ACS
    variance = sum((x - avg_acs) ** 2 for x in acs_list) / len(acs_list)
    std_acs = math.sqrt(variance)
    if std_acs < 10: std_acs = 10  # Защита от деления на ноль, если у всех одинаковый ACS

    for uid in all_ids:
        s = stats_by_id.get(uid, {})
        acs = s.get("acs", avg_acs)
        d = max(s.get("deaths", 1), 1)
        kd = s.get("kills", 0) / d

        # Z-Score ACS (Насколько далеко игрок от среднего значения по лобби)
        z_acs = (acs - avg_acs) / std_acs

        # Разница K/D от среднего по лобби
        diff_kd = kd - avg_kd

        # Combined Performance Index (Смешиваем урон и чистые убийства)
        # 60% веса на разницу ACS, 80% (коэффициент) на чистое КД
        cpi = (z_acs * 0.6) + (diff_kd * 0.8)

        # Переводим индекс в множитель: база 1.0 ± 0.3 за каждую единицу импакта
        p_m = 1.0 + (cpi * 0.3)

        # Ограничиваем влияние от 0.5 (полный руин) до 1.5 (жесткий кери)
        multipliers[uid] = max(0.5, min(1.5, p_m))

    return multipliers

# ==========================================
# ОСНОВНАЯ ФУНКЦИЯ ОБНОВЛЕНИЯ
# ==========================================

def update_elos_after_match(
    winner_ids: list[int],
    loser_ids: list[int],
    stats_by_id: dict[int, dict] = None,
    score_winner: int = 13,
    score_loser: int = 7
) -> dict[int, dict]:
    """
    Обновляет ELO всех игроков после матча с учетом всей продвинутой логики.
    """
    if stats_by_id is None: stats_by_id = {}
    data = _load()
    changes = {}

    all_ids = winner_ids + loser_ids
    if not all_ids: return changes

    # 1. Считаем ELO команд
    team_w_elo = _calculate_team_elo(winner_ids, data)
    team_l_elo = _calculate_team_elo(loser_ids, data)

    # 2. Ожидаемая вероятность победы (Expected Outcome)
    # Формула Эло: E_w = 1 / (1 + 10^((Elo_L - Elo_W) / 400))
    expected_w = 1 / (1 + math.pow(10, (team_l_elo - team_w_elo) / 400))
    expected_l = 1 - expected_w

    # 3. Множитель разгрома
    mov = _get_mov_multiplier(score_winner, score_loser)

    # 4. Множители личного перформанса
    perf_mults = _calculate_performance_multipliers(stats_by_id, all_ids)

    all_players = [(uid, 1.0, expected_w) for uid in winner_ids] + \
                  [(uid, 0.0, expected_l) for uid in loser_ids]

    for uid, result, expected in all_players:
        key = str(uid)
        if key not in data["players"]: data["players"][key] = {}
        player = data["players"][key]

        old_elo = player.get("custom_elo") or RANK_TO_START_ELO.get(player.get("rank_weight", 0), 1000)
        games_played = player.get("custom_games", 0)

        # Динамический K
        k_factor = _get_k_factor(games_played)

        # Базовое изменение (без учета личного скилла)
        base_delta = k_factor * mov * (result - expected)

        # Применяем множитель перформанса
        p_m = perf_mults.get(uid, 1.0)

        if base_delta > 0:
            # Победил: перевыполнил (p_m > 1) -> получит больше. Недоиграл (p_m < 1) -> получит меньше
            total_delta = base_delta * p_m
        else:
            # Проиграл: используем инверсию (2.0 - p_m).
            # Играл как бог (p_m = 1.5) -> (2.0 - 1.5) = 0.5 -> потеряет в 2 раза меньше очков!
            # Руинил игру (p_m = 0.5) -> (2.0 - 0.5) = 1.5 -> потеряет в 1.5 раза больше очков!
            total_delta = base_delta * (2.0 - p_m)

        total_delta = round(total_delta)
        new_elo = max(100, old_elo + total_delta)

        # Сохраняем стату
        player["custom_elo"] = new_elo
        player["custom_games"] = games_played + 1
        if result == 1.0: player["wins"] = player.get("wins", 0) + 1
        else: player["losses"] = player.get("losses", 0) + 1

        data["players"][key] = player
        changes[uid] = {
            "old": old_elo,
            "new": new_elo,
            "delta": total_delta,
            "perf_mult": round(p_m, 2)
        }

    _save(data)
    return changes

EBLOT_TIERS: list[tuple[int, str, str]] = [
    # (min_elo, emoji, name) — путь от зрителя в хабе до Prime
    (0,    "🪑", "Зритель"),      # смотрит, редко попадает в impact
    (850,  "📢", "Очередник"),    # пишет «+», ищет слот
    (900,  "🎲", "Fill"),         # закрывает дырку в лобби
    (950,  "⚔️", "Стачки"),       # дерётся, но без стабильности
    (1000, "🎯", "Regular"),     # нормальный пикап-игрок
    (1050, "🧩", "Ядро"),         # держит лобби, знает роли
    (1100, "👑", "Хост"),         # уровень организатора
    (1150, "🛡️", "Ветеран"),     # тащит и не руинит
    (1220, "⚡", "Elite"),         # топ сервера
    (1300, "✨", "Eblot Prime"),  # потолок
]


def custom_elo_to_rank(elo: int) -> dict:
    """ELO → звание Eblot: emoji, name, label."""
    tier = EBLOT_TIERS[0]
    for min_elo, emoji, name in EBLOT_TIERS:
        if elo >= min_elo:
            tier = (min_elo, emoji, name)
        else:
            break
    _, emoji, name = tier
    return {"emoji": emoji, "name": name, "label": f"{emoji} {name}"}


def custom_elo_to_rank_label(elo: int) -> str:
    """Короткая метка для embed-ов."""
    return custom_elo_to_rank(elo)["label"]

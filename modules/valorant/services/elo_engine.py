"""Custom ELO after Valorant customs: delta math and Eblot rank labels."""

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

# ==========================================
# ╨п╨Ф╨а╨Ю ╨Ь╨Р╨в╨Х╨Ь╨Р╨в╨Ш╨Ъ╨Ш ╨б╨Ш╨б╨в╨Х╨Ь╨л
# ==========================================

def _get_k_factor(games_played: int) -> int:
    """╨Ф╨╕╨╜╨░╨╝╨╕╤З╨╡╤Б╨║╨░╤П ╨▓╨╛╨╗╨░╤В╨╕╨╗╤М╨╜╨╛╤Б╤В╤М: ╨╜╨╛╨▓╨╕╤З╨║╨╕ ╨║╨░╨╗╨╕╨▒╤А╤Г╤О╤В╤Б╤П ╨▒╤Л╤Б╤В╤А╨╡╨╡."""
    if games_played < 10: return 50
    if games_played < 25: return 35
    return 20

def _get_mov_multiplier(score_winner: int, score_loser: int) -> float:
    """╨Ь╨╜╨╛╨╢╨╕╤В╨╡╨╗╤М ╤А╨░╨╖╨╜╨╕╤Ж╤Л ╤А╨░╤Г╨╜╨┤╨╛╨▓. 13:12 = 0.57x | 13:6 = 0.93x | 13:0 = 1.30x"""
    if score_winner is None or score_loser is None:
        return 1.0  # ╨Х╤Б╨╗╨╕ ╤Б╤З╨╡╤В ╨╜╨╡ ╤Г╨║╨░╨╖╨░╨╜ (╨▓╨▓╨╡╨╗╨╕ ╨▓╤А╤Г╤З╨╜╤Г╤О ╨▒╨╡╨╖ ╤Б╤З╨╡╤В╨░)

    diff = abs(score_winner - score_loser)
    # ╨д╨╛╤А╨╝╤Г╨╗╨░, ╨│╨░╤Б╤П╤Й╨░╤П ╨┐╨╛╤В╨╜╤Л╨╡ ╨║╨░╤В╨║╨╕ ╨╕ ╨▒╤Г╤Б╤В╤П╤Й╨░╤П ╤А╨░╨╖╨│╤А╨╛╨╝╤Л
    return 0.5 + (min(diff, 13) / 13.0) * 0.8

def _calculate_team_elo(team_ids: list, data: dict) -> float:
    """╨б╤З╨╕╤В╨░╨╡╤В ╤Б╤А╨╡╨┤╨╜╨╡╨╡ ELO ╨║╨╛╨╝╨░╨╜╨┤╤Л."""
    if not team_ids: return 1000.0
    total = 0
    for uid in team_ids:
        p = data["players"].get(str(uid), {})
        total += p.get("custom_elo") or RANK_TO_START_ELO.get(p.get("rank_weight", 0), 1000)
    return total / len(team_ids)

def _calculate_performance_multipliers(stats_by_id: dict, all_ids: list) -> dict:
    """
    ╨Т╤Л╤З╨╕╤Б╨╗╤П╨╡╤В ╨╝╨╜╨╛╨╢╨╕╤В╨╡╨╗╤М ╨┐╨╡╤А╤Д╨╛╤А╨╝╨░╨╜╤Б╨░ (P_M) ╨┤╨╗╤П ╨║╨░╨╢╨┤╨╛╨│╨╛ ╨╕╨│╤А╨╛╨║╨░ ╤З╨╡╤А╨╡╨╖ Z-Score ╨╗╨╛╨▒╨▒╨╕.
    ╨Т╨╛╨╖╨▓╤А╨░╤Й╨░╨╡╤В: {discord_id: float (╨╛╤В 0.5 ╨┤╨╛ 1.5)}
    """
    multipliers = {uid: 1.0 for uid in all_ids}
    if not stats_by_id: return multipliers

    # ╨б╨╛╨▒╨╕╤А╨░╨╡╨╝ ╨┤╨░╨╜╨╜╤Л╨╡ ╨╗╨╛╨▒╨▒╨╕
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

    # ╨б╤В╨░╨╜╨┤╨░╤А╤В╨╜╨╛╨╡ ╨╛╤В╨║╨╗╨╛╨╜╨╡╨╜╨╕╨╡ ACS
    variance = sum((x - avg_acs) ** 2 for x in acs_list) / len(acs_list)
    std_acs = math.sqrt(variance)
    if std_acs < 10: std_acs = 10  # ╨Ч╨░╤Й╨╕╤В╨░ ╨╛╤В ╨┤╨╡╨╗╨╡╨╜╨╕╤П ╨╜╨░ ╨╜╨╛╨╗╤М, ╨╡╤Б╨╗╨╕ ╤Г ╨▓╤Б╨╡╤Е ╨╛╨┤╨╕╨╜╨░╨║╨╛╨▓╤Л╨╣ ACS

    for uid in all_ids:
        s = stats_by_id.get(uid, {})
        acs = s.get("acs", avg_acs)
        d = max(s.get("deaths", 1), 1)
        kd = s.get("kills", 0) / d

        # Z-Score ACS (╨Э╨░╤Б╨║╨╛╨╗╤М╨║╨╛ ╨┤╨░╨╗╨╡╨║╨╛ ╨╕╨│╤А╨╛╨║ ╨╛╤В ╤Б╤А╨╡╨┤╨╜╨╡╨│╨╛ ╨╖╨╜╨░╤З╨╡╨╜╨╕╤П ╨┐╨╛ ╨╗╨╛╨▒╨▒╨╕)
        z_acs = (acs - avg_acs) / std_acs

        # ╨а╨░╨╖╨╜╨╕╤Ж╨░ K/D ╨╛╤В ╤Б╤А╨╡╨┤╨╜╨╡╨│╨╛ ╨┐╨╛ ╨╗╨╛╨▒╨▒╨╕
        diff_kd = kd - avg_kd

        # Combined Performance Index (╨б╨╝╨╡╤И╨╕╨▓╨░╨╡╨╝ ╤Г╤А╨╛╨╜ ╨╕ ╤З╨╕╤Б╤В╤Л╨╡ ╤Г╨▒╨╕╨╣╤Б╤В╨▓╨░)
        # 60% ╨▓╨╡╤Б╨░ ╨╜╨░ ╤А╨░╨╖╨╜╨╕╤Ж╤Г ACS, 80% (╨║╨╛╤Н╤Д╤Д╨╕╤Ж╨╕╨╡╨╜╤В) ╨╜╨░ ╤З╨╕╤Б╤В╨╛╨╡ ╨Ъ╨Ф
        cpi = (z_acs * 0.6) + (diff_kd * 0.8)

        # ╨Я╨╡╤А╨╡╨▓╨╛╨┤╨╕╨╝ ╨╕╨╜╨┤╨╡╨║╤Б ╨▓ ╨╝╨╜╨╛╨╢╨╕╤В╨╡╨╗╤М: ╨▒╨░╨╖╨░ 1.0 ┬▒ 0.3 ╨╖╨░ ╨║╨░╨╢╨┤╤Г╤О ╨╡╨┤╨╕╨╜╨╕╤Ж╤Г ╨╕╨╝╨┐╨░╨║╤В╨░
        p_m = 1.0 + (cpi * 0.3)

        # ╨Ю╨│╤А╨░╨╜╨╕╤З╨╕╨▓╨░╨╡╨╝ ╨▓╨╗╨╕╤П╨╜╨╕╨╡ ╨╛╤В 0.5 (╨┐╨╛╨╗╨╜╤Л╨╣ ╤А╤Г╨╕╨╜) ╨┤╨╛ 1.5 (╨╢╨╡╤Б╤В╨║╨╕╨╣ ╨║╨╡╤А╨╕)
        multipliers[uid] = max(0.5, min(1.5, p_m))

    return multipliers

# ==========================================
# ╨Ю╨б╨Э╨Ю╨Т╨Э╨Р╨п ╨д╨г╨Э╨Ъ╨ж╨Ш╨п ╨Ю╨С╨Э╨Ю╨Т╨Ы╨Х╨Э╨Ш╨п
# ==========================================

def update_elos_after_match(
    winner_ids: list[int],
    loser_ids: list[int],
    stats_by_id: dict[int, dict] = None,
    score_winner: int = 13,
    score_loser: int = 7
) -> dict[int, dict]:
    """
    ╨Ю╨▒╨╜╨╛╨▓╨╗╤П╨╡╤В ELO ╨▓╤Б╨╡╤Е ╨╕╨│╤А╨╛╨║╨╛╨▓ ╨┐╨╛╤Б╨╗╨╡ ╨╝╨░╤В╤З╨░ ╤Б ╤Г╤З╨╡╤В╨╛╨╝ ╨▓╤Б╨╡╨╣ ╨┐╤А╨╛╨┤╨▓╨╕╨╜╤Г╤В╨╛╨╣ ╨╗╨╛╨│╨╕╨║╨╕.
    """
    if stats_by_id is None: stats_by_id = {}
    data = _load()
    changes = {}

    all_ids = winner_ids + loser_ids
    if not all_ids: return changes

    # 1. ╨б╤З╨╕╤В╨░╨╡╨╝ ELO ╨║╨╛╨╝╨░╨╜╨┤
    team_w_elo = _calculate_team_elo(winner_ids, data)
    team_l_elo = _calculate_team_elo(loser_ids, data)

    # 2. ╨Ю╨╢╨╕╨┤╨░╨╡╨╝╨░╤П ╨▓╨╡╤А╨╛╤П╤В╨╜╨╛╤Б╤В╤М ╨┐╨╛╨▒╨╡╨┤╤Л (Expected Outcome)
    # ╨д╨╛╤А╨╝╤Г╨╗╨░ ╨н╨╗╨╛: E_w = 1 / (1 + 10^((Elo_L - Elo_W) / 400))
    expected_w = 1 / (1 + math.pow(10, (team_l_elo - team_w_elo) / 400))
    expected_l = 1 - expected_w

    # 3. ╨Ь╨╜╨╛╨╢╨╕╤В╨╡╨╗╤М ╤А╨░╨╖╨│╤А╨╛╨╝╨░
    mov = _get_mov_multiplier(score_winner, score_loser)

    # 4. ╨Ь╨╜╨╛╨╢╨╕╤В╨╡╨╗╨╕ ╨╗╨╕╤З╨╜╨╛╨│╨╛ ╨┐╨╡╤А╤Д╨╛╤А╨╝╨░╨╜╤Б╨░
    perf_mults = _calculate_performance_multipliers(stats_by_id, all_ids)

    all_players = [(uid, 1.0, expected_w) for uid in winner_ids] + \
                  [(uid, 0.0, expected_l) for uid in loser_ids]

    for uid, result, expected in all_players:
        key = str(uid)
        if key not in data["players"]: data["players"][key] = {}
        player = data["players"][key]

        old_elo = player.get("custom_elo") or RANK_TO_START_ELO.get(player.get("rank_weight", 0), 1000)
        games_played = player.get("custom_games", 0)

        # ╨Ф╨╕╨╜╨░╨╝╨╕╤З╨╡╤Б╨║╨╕╨╣ K
        k_factor = _get_k_factor(games_played)

        # ╨С╨░╨╖╨╛╨▓╨╛╨╡ ╨╕╨╖╨╝╨╡╨╜╨╡╨╜╨╕╨╡ (╨▒╨╡╨╖ ╤Г╤З╨╡╤В╨░ ╨╗╨╕╤З╨╜╨╛╨│╨╛ ╤Б╨║╨╕╨╗╨╗╨░)
        base_delta = k_factor * mov * (result - expected)

        # ╨Я╤А╨╕╨╝╨╡╨╜╤П╨╡╨╝ ╨╝╨╜╨╛╨╢╨╕╤В╨╡╨╗╤М ╨┐╨╡╤А╤Д╨╛╤А╨╝╨░╨╜╤Б╨░
        p_m = perf_mults.get(uid, 1.0)

        if base_delta > 0:
            # ╨Я╨╛╨▒╨╡╨┤╨╕╨╗: ╨┐╨╡╤А╨╡╨▓╤Л╨┐╨╛╨╗╨╜╨╕╨╗ (p_m > 1) -> ╨┐╨╛╨╗╤Г╤З╨╕╤В ╨▒╨╛╨╗╤М╤И╨╡. ╨Э╨╡╨┤╨╛╨╕╨│╤А╨░╨╗ (p_m < 1) -> ╨┐╨╛╨╗╤Г╤З╨╕╤В ╨╝╨╡╨╜╤М╤И╨╡
            total_delta = base_delta * p_m
        else:
            # ╨Я╤А╨╛╨╕╨│╤А╨░╨╗: ╨╕╤Б╨┐╨╛╨╗╤М╨╖╤Г╨╡╨╝ ╨╕╨╜╨▓╨╡╤А╤Б╨╕╤О (2.0 - p_m).
            # ╨Ш╨│╤А╨░╨╗ ╨║╨░╨║ ╨▒╨╛╨│ (p_m = 1.5) -> (2.0 - 1.5) = 0.5 -> ╨┐╨╛╤В╨╡╤А╤П╨╡╤В ╨▓ 2 ╤А╨░╨╖╨░ ╨╝╨╡╨╜╤М╤И╨╡ ╨╛╤З╨║╨╛╨▓!
            # ╨а╤Г╨╕╨╜╨╕╨╗ ╨╕╨│╤А╤Г (p_m = 0.5) -> (2.0 - 0.5) = 1.5 -> ╨┐╨╛╤В╨╡╤А╤П╨╡╤В ╨▓ 1.5 ╤А╨░╨╖╨░ ╨▒╨╛╨╗╤М╤И╨╡ ╨╛╤З╨║╨╛╨▓!
            total_delta = base_delta * (2.0 - p_m)

        total_delta = round(total_delta)
        new_elo = max(100, old_elo + total_delta)

        # ╨б╨╛╤Е╤А╨░╨╜╤П╨╡╨╝ ╤Б╤В╨░╤В╤Г
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
    # (min_elo, emoji, name) тАФ ╨┐╤Г╤В╤М ╨╛╤В ╨╖╤А╨╕╤В╨╡╨╗╤П ╨▓ ╤Е╨░╨▒╨╡ ╨┤╨╛ Prime
    (0,    "ЁЯеЪ", "╨Х╨▒╨╗╨╛╤В-╨╖╨░╤А╨╛╨┤╤Л╤И"),
    (850,  "ЁЯС╢", "╨Ь╨╕╨║╤А╨╛╤З╨╡╨╗"),
    (900,  "ЁЯз╜", "╨Я╨╡╨╜╨╛╨┐╨╗╨░╤Б╤В╨╛╨▓╤Л╨╣ ╨░╨╕╨╝"),
    (950,  "ЁЯЪ╢тАНтЩВя╕П", "╨С╨╡╨│╤Г ╨╕ ╤Б╤В╤А╨╡╨╗╤П╤О"),  # Run & Gun
    (1000, "ЁЯОп", "╨Ь╨░╨│╨╜╨╕╤В ╨┤╨╗╤П ╨┐╤Г╨╗╤М"),
    (1050, "ЁЯТк", "╨в╨░╤Й╨╕╨╗╨░ (╨╜╨░ ╤Б╨╗╨╛╨▓╨░╤Е)"),
    (1100, "ЁЯФе", "╨Ъ╨╗╨░╤В╤З-╨╝╨░╤И╨╕╨╜╨░"),
    (1150, "ЁЯж╕", "╨У╨╕╨│╨░╤З╨░╨┤"),
    (1220, "тЪб", "╨а╤Г╤З╨╛╨╜╨║╨░ ╨Х╨▒╨╗╨╛╤А╨┤╨░"),
    (1300, "тЬи", "Eblord"),
]

def custom_elo_to_rank(elo: int) -> dict:
    """ELO тЖТ ╨╖╨▓╨░╨╜╨╕╨╡ Eblot: emoji, name, label."""
    tier = EBLOT_TIERS[0]
    for min_elo, emoji, name in EBLOT_TIERS:
        if elo >= min_elo:
            tier = (min_elo, emoji, name)
        else:
            break
    _, emoji, name = tier
    return {"emoji": emoji, "name": name, "label": f"{emoji} {name}"}


def custom_elo_to_rank_label(elo: int) -> str:
    """╨Ъ╨╛╤А╨╛╤В╨║╨░╤П ╨╝╨╡╤В╨║╨░ ╨┤╨╗╤П embed-╨╛╨▓."""
    return custom_elo_to_rank(elo)["label"]

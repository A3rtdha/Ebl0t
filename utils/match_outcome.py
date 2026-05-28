"""Победитель (команда 1/2) и счёт матча — поверх OCR / ручного ввода."""

from __future__ import annotations

from typing import Any


def team_label(team_num: int, match_data: dict) -> str:
    team1_side = match_data.get("team1_side", "attack")
    team2_side = "defense" if team1_side == "attack" else "attack"
    side = team1_side if team_num == 1 else team2_side
    side_ru = "Атака" if side == "attack" else "Защита"
    icon = "🔵" if team_num == 1 else "🔴"
    n = len(match_data.get(f"team{team_num}_ids") or [])
    return f"{icon} Команда {team_num} ({side_ru}, {n} чел.)"


def apply_team_outcome(
    parsed: dict,
    match_data: dict,
    winner_team: int,
    score_winner: int,
    score_loser: int,
) -> dict:
    """Записывает winner_team и счёт; синхронизирует winner/score_attack/defense для embed."""
    parsed = dict(parsed)
    parsed["winner_team"] = winner_team
    parsed["score_winner"] = score_winner
    parsed["score_loser"] = score_loser

    team1_side = match_data.get("team1_side", "attack")
    team2_side = "defense" if team1_side == "attack" else "attack"
    parsed["winner"] = team1_side if winner_team == 1 else team2_side

    if team1_side == "attack":
        if winner_team == 1:
            parsed["score_attack"], parsed["score_defense"] = score_winner, score_loser
        else:
            parsed["score_attack"], parsed["score_defense"] = score_loser, score_winner
    else:
        if winner_team == 1:
            parsed["score_attack"], parsed["score_defense"] = score_loser, score_winner
        else:
            parsed["score_attack"], parsed["score_defense"] = score_winner, score_loser

    return parsed


def guess_winner_team_from_parsed(parsed: dict, match_data: dict) -> int | None:
    """Пытается угадать команду-победителя из OCR (сторона атака/защита)."""
    winner_side = parsed.get("winner")
    if winner_side not in ("attack", "defense"):
        return parsed.get("winner_team")
    team1_side = match_data.get("team1_side", "attack")
    if winner_side == team1_side:
        return 1
    if winner_side == ("defense" if team1_side == "attack" else "attack"):
        return 2
    return None


def guess_score_from_parsed(parsed: dict) -> tuple[int, int] | None:
    """Счёт победителя : проигравшего из OCR."""
    sa, sd = parsed.get("score_attack"), parsed.get("score_defense")
    try:
        sa, sd = int(sa), int(sd)
    except (TypeError, ValueError):
        return None
    winner_side = parsed.get("winner")
    team1_side = "attack"  # only need relative winner/loser rounds
    if winner_side == "attack":
        return (sa, sd) if sa >= sd else (sd, sa)
    if winner_side == "defense":
        return (sd, sa) if sd >= sa else (sa, sd)
    return (max(sa, sd), min(sa, sd))


SCORE_PRESETS: list[tuple[str, int, int]] = [
    (f"{w}:{l}", w, l)
    for w, l in [
        (13, 0), (13, 1), (13, 2), (13, 3), (13, 4), (13, 5), (13, 6), (13, 7),
        (13, 8), (13, 9), (13, 10), (13, 11), (13, 12),
        (12, 14), (11, 13),
    ]
]

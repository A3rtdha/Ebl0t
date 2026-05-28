#!/usr/bin/env python3
"""
Разовый прогон ELO по scoreboard со скрина (когда OCR облажался).
Запуск из Eblot/:  python scripts/apply_match_from_screen.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils import db_manager, elo_engine
from utils.manual_scoreboard import parse_manual_scoreboard

# Скрин: 5 победителей (тёмно-красные + MVP), 4 проигравших (бирюзовые)
# little dachshund нет в БД — пропуск
SCREEN_TEXT = """
9:13
защита
big Dobermann|17|13|2|311|защита
Пальцы в розетке|18|7|8|276|защита
Клайд|15|8|4|238|защита
рыцарь кухни|10|9|3|168|защита
залетаю в толпу|11|8|2|158|защита
Бонни|13|15|2|214|атака
Ренегат|7|15|3|144|атака
zera4kka|5|16|2|111|атака
little dachshund|5|10|6|103|атака
""".strip()

# discord_id по riot_name из data.json
NAME_TO_ID = {
    "big dobermann": 634414560266158112,
    "пальцы в розетке": 234268189691740162,
    "клайд": 586938958026375171,
    "рыцарь кухни": 590933336705204238,
    "залетаю в толпу": 1337350644469727244,
    "бонни": 863016228339318804,
    "ренегат": 741317473546010734,
    "zera4kka": 341872680691302401,
}

REVERT_RYTSAR = 590933336705204238  # откат кривого OCR-матча


def undo_last_match(discord_id: int):
    """Снимает последнюю запись match_history и откатывает custom_elo на delta."""
    p = db_manager.get_player(discord_id)
    if not p or not p.get("match_history"):
        return False
    last = p["match_history"][-1]
    delta = last.get("elo_delta", 0)
    data = db_manager._load()
    key = str(discord_id)
    pl = data["players"][key]
    pl["match_history"] = pl["match_history"][:-1]
    if pl.get("custom_elo") is not None:
        pl["custom_elo"] = max(100, pl["custom_elo"] - delta)
    pl["custom_games"] = max(0, pl.get("custom_games", 1) - 1)
    if last.get("result") == "win":
        pl["wins"] = max(0, pl.get("wins", 0) - 1)
    else:
        pl["losses"] = max(0, pl.get("losses", 0) - 1)
    if pl["custom_games"] == 0:
        pl["custom_elo"] = None
    db_manager._save(data)
    return True


def _find_discord_id(riot_id: str) -> int | None:
    name = riot_id.split("#")[0].strip().lower()
    if name in NAME_TO_ID:
        return NAME_TO_ID[name]
    all_p = db_manager.get_all_players()
    for uid, p in all_p.items():
        if (p.get("riot_name") or "").lower() == name:
            return int(uid)
    return None


def revert_bad_match(discord_id: int):
    p = db_manager.get_player(discord_id)
    if not p or not p.get("match_history"):
        return
    last = p["match_history"][-1]
    if last.get("elo_delta") != 12:
        print(f"  skip revert {discord_id}: last delta {last.get('elo_delta')}")
        return
    data = db_manager._load()
    key = str(discord_id)
    pl = data["players"][key]
    pl["match_history"] = pl["match_history"][:-1]
    pl["custom_elo"] = None
    pl["custom_games"] = max(0, pl.get("custom_games", 1) - 1)
    pl["wins"] = max(0, pl.get("wins", 0) - 1)
    db_manager._save(data)
    print(f"  reverted bogus match for {pl.get('riot_name')}")


def main():
    import os
    if os.environ.get("UNDO_LAST") == "1":
        print("=== Откат последнего прогона ===")
        for uid in NAME_TO_ID.values():
            if undo_last_match(uid):
                print(f"  undone {uid}")
        return

    print("=== Откат ошибочного OCR-матча (рыцарь кухни) ===")
    revert_bad_match(REVERT_RYTSAR)

    parsed = parse_manual_scoreboard(SCREEN_TEXT)
    if not parsed:
        print("parse failed")
        sys.exit(1)

    winner_side = parsed["winner"]
    matched_stats: dict[int, dict] = {}
    winner_ids: list[int] = []
    loser_ids: list[int] = []

    for pl in parsed["players"]:
        uid = _find_discord_id(pl["riot_id"])
        if uid is None:
            print(f"  skip (no discord): {pl['riot_id']}")
            continue
        stats = {
            "team": pl["team"],
            "kills": pl["kills"],
            "deaths": pl["deaths"],
            "assists": pl["assists"],
            "acs": pl["acs"],
            "hs_percent": None,
        }
        matched_stats[uid] = stats
        if pl["team"] == winner_side:
            winner_ids.append(uid)
        else:
            loser_ids.append(uid)

    sa, sd = int(parsed["score_attack"]), int(parsed["score_defense"])
    if winner_side == "attack":
        score_winner, score_loser = sa, sd
    else:
        score_winner, score_loser = sd, sa

    print(f"\n=== ELO: winners={len(winner_ids)} losers={len(loser_ids)} score {score_winner}:{score_loser} ===")
    changes = elo_engine.update_elos_after_match(
        winner_ids=winner_ids,
        loser_ids=loser_ids,
        stats_by_id=matched_stats,
        score_winner=score_winner,
        score_loser=score_loser,
    )

    db_manager.record_match_result(
        winner_ids=winner_ids,
        loser_ids=loser_ids,
        stats_by_id=matched_stats,
        elo_changes=changes,
    )

    for uid, ch in sorted(changes.items(), key=lambda x: -x[1]["new"]):
        p = db_manager.get_player(uid)
        name = p.get("riot_name", uid) if p else uid
        sign = "+" if ch["delta"] >= 0 else ""
        print(
            f"  {'W' if uid in winner_ids else 'L'} {name}: "
            f"{ch['old']} -> {ch['new']} ({sign}{ch['delta']})"
        )


if __name__ == "__main__":
    main()

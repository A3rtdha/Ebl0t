#!/usr/bin/env python3
"""
Тест OCR scoreboard — ничего не пишет в data.json.

  cd Eblot
  python scripts/test_screenshot_parse.py
  python scripts/test_screenshot_parse.py "Screenshot 2026-05-28 230045.png"
  python scripts/test_screenshot_parse.py "путь/к/скрину.png" --rows   # только сетка строк
  python scripts/test_screenshot_parse.py --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.valorant.services import screenshot_parser

DEFAULT_IMAGE = ROOT / "Screenshot 2026-05-28 230045.png"

# Эталон со скрина 2026-05-28 (для сравнения в консоли)
EXPECTED = [
    ("big Dobermann", 17, 13, 2, 311, "attack"),
    ("Пальцы в розетке", 18, 7, 8, 276, "attack"),
    ("Клайд", 15, 8, 4, 238, "attack"),
    ("Бонни", 13, 15, 2, 214, "defense"),
    ("рыцарь кухни", 10, 9, 3, 168, "defense"),
    ("залетаю в толпу", 11, 8, 2, 158, "attack"),
    ("Ренегат", 7, 15, 3, 144, "defense"),
    ("zera4kka", 5, 16, 2, 111, "defense"),
    ("little dachshund", 5, 10, 6, 103, "attack"),
]


def _norm_name(s: str) -> str:
    return (s or "").lower().split("#")[0].strip()


def _print_report(parsed: dict, row_count: int | None = None) -> None:
    print("=" * 60)
    if row_count is not None:
        print(f"Строк в сетке (авто): {row_count}")
    print(f"host_won: {parsed.get('host_won')}")
    print(f"winner (side): {parsed.get('winner')}")
    print(f"score: {parsed.get('score_attack')} : {parsed.get('score_defense')}")
    print("-" * 60)

    players = parsed.get("players") or []
    exp_by_key = {_norm_name(n): (n, k, d, a, acs, t) for n, k, d, a, acs, t in EXPECTED}

    for i, p in enumerate(players, 1):
        nick = p.get("riot_id", "?")
        k, d, a, acs = p.get("kills"), p.get("deaths"), p.get("assists"), p.get("acs")
        team = p.get("team")
        key = _norm_name(nick)
        ok = ""
        for ek, ev in exp_by_key.items():
            if ek in key or key in ek:
                en, ek0, ed, ea, eacs, et = ev
                mism = []
                if (k, d, a, acs) != (ek0, ed, ea, eacs):
                    mism.append(f"KDA/ACS want {ek0}/{ed}/{ea}/{eacs}")
                if team != et:
                    mism.append(f"team want {et}")
                ok = "OK" if not mism else " | ".join(mism)
                break
        if not ok:
            ok = "(no expected match)"
        print(f"{i:2}. [{team:7}] {nick:28} {k:2}/{d:2}/{a:2} ACS:{acs:3}  {ok}")

    print("-" * 60)
    print(f"Игроков распознано: {len(players)} / {len(EXPECTED)}")


async def main() -> int:
    ap = argparse.ArgumentParser(description="Тест парсера скриншота (без сохранения в БД)")
    ap.add_argument("image", nargs="?", default=str(DEFAULT_IMAGE), help="Путь к PNG/JPG")
    ap.add_argument("--json", action="store_true", help="Вывести сырой JSON")
    ap.add_argument("--rows", action="store_true", help="Только показать детект строк")
    args = ap.parse_args()

    path = Path(args.image)
    if not path.is_file():
        print(f"Файл не найден: {path}", file=sys.stderr)
        return 1

    import cv2

    data = path.read_bytes()
    if args.rows:
        arr = __import__("numpy").frombuffer(data, dtype=__import__("numpy").uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        centers, rh = screenshot_parser._detect_scoreboard_rows(img)
        print(f"File: {path.name} -> {len(centers)} rows, half_h={rh:.4f}")
        for i, cy in enumerate(centers, 1):
            print(f"  {i}: y={cy:.4f}")
        return 0

    parsed = await screenshot_parser.parse_screenshot(data)

    if parsed is None:
        print("parse_screenshot вернул None")
        return 2

    if args.json:
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
    else:
        _print_report(parsed, row_count=len(parsed.get("players") or []))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

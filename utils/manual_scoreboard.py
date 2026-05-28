"""
Парсинг ручного ввода scoreboard после кривого OCR.
Формат (первая строка — счёт, вторая — победитель, дальше игроки):

13:9
защита
Ник|K|D|A|ACS|защита
big Dobermann|17|13|2|311|защита
...
"""

from __future__ import annotations

import re
from typing import Any


_SIDE_ALIASES = {
    "attack": "attack",
    "attacker": "attack",
    "атака": "attack",
    "atk": "attack",
    "defense": "defense",
    "defender": "defense",
    "defence": "defense",
    "защита": "defense",
    "def": "defense",
}

_WINNER_ALIASES = _SIDE_ALIASES


def _norm_side(raw: str) -> str | None:
    if not raw:
        return None
    return _SIDE_ALIASES.get(raw.strip().lower().replace("ё", "е"))


def parsed_to_manual_text(parsed: dict) -> str:
    """Собирает текст для модалки из результата OCR."""
    lines: list[str] = []
    sa = parsed.get("score_attack")
    sd = parsed.get("score_defense")
    if sa is not None and sd is not None and str(sa).isdigit() and str(sd).isdigit():
        lines.append(f"{sa}:{sd}")
    else:
        lines.append("13:9")

    winner = parsed.get("winner") or "defense"
    lines.append("защита" if winner == "defense" else "атака")

    for p in parsed.get("players") or []:
        riot_id = (p.get("riot_id") or "?").strip()
        team = p.get("team") or "attack"
        side = "атака" if team == "attack" else "защита"
        lines.append(
            f"{riot_id}|{p.get('kills', 0)}|{p.get('deaths', 0)}|"
            f"{p.get('assists', 0)}|{p.get('acs', 0)}|{side}"
        )
    return "\n".join(lines)


def parse_manual_scoreboard(text: str) -> dict | None:
  """
  Возвращает dict в формате screenshot_parser:
  {winner, score_attack, score_defense, host_won, players: [...]}

  Счёт и победитель задаются отдельным шагом (MatchOutcomeView).
  Можно вставить только строки игроков: Ник|K|D|A|ACS|атака
  """
  lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
  if not lines:
      return None

  score_attack, score_defense = 13, 9
  idx = 0
  winner = "attack"

  # Только статистика игроков — без заголовка счёта
  if "|" in lines[0]:
      idx = 0
  else:
      m = re.match(r"(\d+)\s*[:;]\s*(\d+)", lines[0])
      if m:
          score_attack, score_defense = int(m.group(1)), int(m.group(2))
          idx = 1
      if idx < len(lines):
          w = _norm_side(lines[idx])
          if w is not None:
              winner = w
              idx += 1

  players: list[dict[str, Any]] = []
  for line in lines[idx:]:
      parts = [p.strip() for p in line.split("|")]
      if len(parts) < 5:
          continue
      riot_id = parts[0]
      try:
          kills = int(parts[1])
          deaths = int(parts[2])
          assists = int(parts[3])
          acs = int(parts[4])
      except ValueError:
          continue
      team = _norm_side(parts[5]) if len(parts) > 5 else "attack"
      if team is None:
          team = "attack"
      players.append({
          "riot_id": riot_id,
          "kills": kills,
          "deaths": deaths,
          "assists": assists,
          "acs": acs,
          "team": team,
          "hs_percent": None,
      })

  if not players:
      return None

  return {
      "winner": winner,
      "score_attack": score_attack,
      "score_defense": score_defense,
      "host_won": None,
      "players": players,
  }


MANUAL_FORMAT_HELP = (
    "**Формат** — по строке на игрока (счёт и победитель выберешь кнопками после):\n"
    "```\n"
    "Ник|K|D|A|ACS|защита\n"
    "big Dobermann|17|13|2|311|защита\n"
    "```\n"
    "Сторона в конце: `атака` или `защита` (как на скрине)."
)

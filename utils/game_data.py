"""
game_data.py — читает карты и агентов из data/game_data.json.
Чтобы добавить нового агента или карту — просто правь JSON файл, не трогая код.
"""
import json
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "game_data.json")

def _load():
    with open(_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def get_maps() -> list[str]:
    return _load()["maps"]

def get_agents(role: str = "Все") -> list[str]:
    return _load()["agents"].get(role, _load()["agents"]["Все"])

# Обратная совместимость — старый код использовал MAP_POOL и AGENT_POOL напрямую
MAP_POOL   = get_maps()
AGENT_POOL = get_agents()

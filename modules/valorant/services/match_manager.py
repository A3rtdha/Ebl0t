"""Активные матчи Valorant в JSON (переживают рестарт бота, ГК — не всегда)."""

import json
import os
import time
import logging

log = logging.getLogger(__name__)

from core.paths import ACTIVE_MATCHES_JSON

_MATCHES_PATH = str(ACTIVE_MATCHES_JSON)


def _load() -> dict:
    if not os.path.exists(_MATCHES_PATH):
        return {}
    try:
        with open(_MATCHES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict):
    os.makedirs(os.path.dirname(_MATCHES_PATH), exist_ok=True)
    with open(_MATCHES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_active_match(
    host_id: int,
    team1_channel_id: int,
    team2_channel_id: int,
    lobby_id: int,
    team1_ids: list = None,
    team2_ids: list = None,
    team1_side: str = "attack",
    dashboard_msg_id: int | None = None,
    text_channel_id: int | None = None,
    map_name: str | None = None,
):
    data = _load()
    data[str(host_id)] = {
        "host_id":    host_id,
        "team1_vc":   team1_channel_id,
        "team2_vc":   team2_channel_id,
        "lobby_id":   lobby_id,
        "team1_ids":  [m.id if hasattr(m, "id") else int(m) for m in (team1_ids or [])],
        "team2_ids":  [m.id if hasattr(m, "id") else int(m) for m in (team2_ids or [])],
        "team1_side": team1_side,
        "dashboard_msg_id": dashboard_msg_id,
        "text_channel_id": text_channel_id,
        "map_name": map_name,
        "started_at": int(time.time()),
    }
    _save(data)
    log.info(f"Матч хоста {host_id} сохранён в {_MATCHES_PATH}")


def get_active_match(host_id: int) -> dict | None:
    return _load().get(str(host_id))


def get_all_active_matches() -> dict:
    """Все активные матчи — для восстановления после перезапуска."""
    return _load()


def remove_active_match(host_id: int):
    data = _load()
    key = str(host_id)
    if key in data:
        del data[key]
        _save(data)
        log.info(f"Матч хоста {host_id} удалён")

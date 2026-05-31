"""Сколько времени участники провели в голосовых каналах сервера (JSON + чекпоинты)."""

import json
import os
import time
import logging

log = logging.getLogger(__name__)

from core.paths import VOICE_ACTIVE_JSON, VOICE_STATS_JSON

_STATS_PATH = str(VOICE_STATS_JSON)
_ACTIVE_PATH = str(VOICE_ACTIVE_JSON)

# (guild_id, user_id) -> unix timestamp начала текущей незакрытой сессии
_active: dict[tuple[int, int], float] = {}


def _load() -> dict:
    if not os.path.exists(_STATS_PATH):
        return {"guilds": {}}
    try:
        with open(_STATS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("guilds", {})
        return data
    except (json.JSONDecodeError, OSError):
        log.warning("voice_stats.json повреждён, создаю заново.")
        return {"guilds": {}}


def _save(data: dict):
    os.makedirs(os.path.dirname(_STATS_PATH), exist_ok=True)
    with open(_STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _guild_bucket(data: dict, guild_id: int) -> dict:
    g = data["guilds"].setdefault(str(guild_id), {"members": {}})
    g.setdefault("members", {})
    return g


def _add_seconds_in_data(data: dict, guild_id: int, user_id: int, delta: int):
    if delta <= 0:
        return
    bucket = _guild_bucket(data, guild_id)
    key = str(user_id)
    member = bucket["members"].setdefault(key, {"total_seconds": 0})
    member["total_seconds"] = int(member.get("total_seconds", 0)) + delta


def _add_seconds_to_member(guild_id: int, user_id: int, delta: int):
    if delta <= 0:
        return
    data = _load()
    _add_seconds_in_data(data, guild_id, user_id, delta)
    _save(data)


def start_session(guild_id: int, user_id: int):
    """Начать сессию; не сбрасывать таймер, если уже в ГК."""
    key = (guild_id, user_id)
    if key not in _active:
        _active[key] = time.time()


def flush_active_sessions() -> int:
    """Сбросить накопленное время из RAM в JSON (сессия в ГК продолжается)."""
    if not _active:
        return 0
    now = time.time()
    flushed = 0
    data = _load()
    for key in list(_active):
        started = _active[key]
        delta = max(0, int(now - started))
        if delta > 0:
            _add_seconds_in_data(data, key[0], key[1], delta)
            flushed += delta
        _active[key] = now
    _save(data)
    _save_active_file()
    return flushed


def _save_active_file():
    payload = {
        "sessions": [
            {"guild_id": gid, "user_id": uid, "started": started}
            for (gid, uid), started in _active.items()
        ]
    }
    os.makedirs(os.path.dirname(_ACTIVE_PATH), exist_ok=True)
    with open(_ACTIVE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_persisted_active(bot) -> None:
    """После рестарта восстановить сессии тех, кто всё ещё в ГК."""
    if not os.path.exists(_ACTIVE_PATH):
        return
    try:
        with open(_ACTIVE_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    data = _load()
    now = time.time()
    for row in payload.get("sessions", []):
        try:
            gid = int(row["guild_id"])
            uid = int(row["user_id"])
            started = float(row["started"])
        except (KeyError, TypeError, ValueError):
            continue
        guild = bot.get_guild(gid)
        if not guild:
            delta = max(0, int(now - started))
            _add_seconds_in_data(data, gid, uid, delta)
            continue
        member = guild.get_member(uid)
        if member and member.voice and member.voice.channel:
            _active[(gid, uid)] = started
        else:
            delta = max(0, int(now - started))
            _add_seconds_in_data(data, gid, uid, delta)

    _save(data)
    _save_active_file()


def end_session(guild_id: int, user_id: int) -> int:
    """Закрывает сессию, возвращает добавленные секунды (0 если не было сессии)."""
    started = _active.pop((guild_id, user_id), None)
    if started is None:
        return 0
    delta = max(0, int(time.time() - started))
    if delta <= 0:
        _save_active_file()
        return 0
    _add_seconds_to_member(guild_id, user_id, delta)
    _save_active_file()
    return delta


def get_total_seconds(guild_id: int, user_id: int) -> int:
    data = _load()
    member = _guild_bucket(data, guild_id)["members"].get(str(user_id), {})
    total = int(member.get("total_seconds", 0))
    started = _active.get((guild_id, user_id))
    if started:
        total += max(0, int(time.time() - started))
    return total


def guild_user_ids(guild_id: int) -> set[int]:
    """Все ID с сохранённым или текущим (в ГК) временем на сервере."""
    data = _load()
    ids = set()
    for uid_str in _guild_bucket(data, guild_id)["members"]:
        try:
            ids.add(int(uid_str))
        except ValueError:
            pass
    for gid, uid in _active:
        if gid == guild_id:
            ids.add(uid)
    return ids


def get_guild_leaderboard(guild_id: int, limit: int = 15) -> list[tuple[int, int]]:
    rows = [
        (uid, get_total_seconds(guild_id, uid))
        for uid in guild_user_ids(guild_id)
    ]
    rows = [(uid, sec) for uid, sec in rows if sec > 0]
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:limit]


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} сек"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} мин" + (f" {sec} сек" if sec else "")
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    return " ".join(parts) if parts else "0 мин"

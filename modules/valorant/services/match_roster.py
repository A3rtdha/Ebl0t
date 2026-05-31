"""Сверка состава кастомки (лобби) с числом игроков на scoreboard."""


def lobby_player_count(match_data: dict) -> int:
    return len(match_data.get("team1_ids", [])) + len(match_data.get("team2_ids", []))


def lobby_roster_label(match_data: dict) -> str:
    t1 = len(match_data.get("team1_ids", []))
    t2 = len(match_data.get("team2_ids", []))
    return f"{t1}v{t2}"


def check_screenshot_vs_lobby(
    match_data: dict,
    parsed: dict,
    *,
    max_drift: int = 1,
) -> tuple[str | None, str | None]:
    """
    Сравнивает число игроков на скрине с составом при START.

    Returns:
        (None, None) — всё ок
        ("warn", msg) — расхождение на 1 (можно продолжить с осторожностью)
        ("block", msg) — сильное расхождение, скрин скорее не от этого матча
    """
    expected = lobby_player_count(match_data)
    on_screen = len(parsed.get("players") or [])
    if expected < 1:
        return None, None

    drift = abs(on_screen - expected)
    label = lobby_roster_label(match_data)
    if drift == 0:
        return None, None
    if drift <= max_drift:
        return "warn", (
            f"На скрине **{on_screen}** игроков, в лобби было **{expected}** ({label}). "
            "Убедись, что это scoreboard **этой** кастомки."
        )
    return "block", (
        f"На скрине **{on_screen}** игроков, а в этой кастомке было **{expected}** ({label}).\n"
        "Похоже, скрин от **другого матча** (например, стандарт 5v5 вместо вашего состава). "
        "Пришли правильный скриншот или жми **ввести вручную**."
    )

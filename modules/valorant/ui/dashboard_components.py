"""Заготовка Components V2 для дашборда (пока не используется в проде)."""

import disnake
from disnake import ui
from modules.valorant.services import valo_logic, db_manager
from shared import ui_theme


def _format_team(team_list, db_data: dict) -> str:
    if not team_list:
        return "—"
    lines = []
    for member in team_list:
        skill = valo_logic.player_skill_elo(member, db_data)
        lines.append(f"{member.mention} · **{skill}**")
    avg = valo_logic.team_average_skill(team_list, db_data)
    if avg:
        lines.append(f"\n*⚖️ Средняя: **{avg}***")
    return "\n".join(lines)


def build_match_dashboard_components(view) -> list:
    """view — MatchDashboardView."""
    is_ready = bool((view.team1 or view.team2) and view.selected_map and view.agent_assignments)
    steps = [
        ("Команды", bool(view.team1 or view.team2)),
        ("Карта", bool(view.selected_map)),
        ("Агенты", bool(view.agent_assignments)),
    ]
    status_line = "  ".join(f"{'✅' if ok else '⬜'} {name}" for name, ok in steps)
    map_val = f"**{view.selected_map}**" if view.selected_map else "*не выбрана*"

    all_players = view.team1 + view.team2
    db_data = db_manager.get_players_bulk([m.id for m in all_players]) if all_players else {}

    header = (
        f"### ⚔️ Настройка матча · {view.mode}\n"
        f"Хост: {view.host.mention}\n"
        f"📍 Карта: {map_val}  ·  {status_line}"
    )
    accent = ui_theme.COLOR_SUCCESS if is_ready else ui_theme.COLOR_PRIMARY

    return [
        ui.Container(
            ui.TextDisplay(header),
            ui.Separator(divider=True),
            ui.TextDisplay(f"**🔵 Атака · {len(view.team1)}**\n{_format_team(view.team1, db_data)}"),
            ui.TextDisplay(f"**🔴 Защита · {len(view.team2)}**\n{_format_team(view.team2, db_data)}"),
            ui.TextDisplay(f"*{ui_theme.BRAND_FOOTER}*"),
            accent_colour=accent,
        )
    ]


def v2_message_flags() -> disnake.MessageFlags:
    return disnake.MessageFlags(is_components_v2=True)

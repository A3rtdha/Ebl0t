"""Post-outcome flow: nick matching wizard, auto-link, ELO finalization."""

from __future__ import annotations

import asyncio
import logging
import uuid

import disnake

from modules.valorant.services import (
    db_manager,
    elo_engine,
    match_roster,
    result_flow_cleanup,
    riot_api,
    screenshot_parser,
)
from modules.valorant.services.match_outcome import guess_winner_team_from_parsed
from modules.valorant.services.result_flow_state import (
    active_result_channels,
    result_flow_locks,
    wizard_sessions,
)
from modules.valorant.ui.finish_views import LinkConfirmView, PickNickView
from modules.valorant.ui.match_outcome import team_label
from shared import ui_theme

log = logging.getLogger(__name__)


async def start_result_flow(channel, host, guild, parsed: dict, match_data: dict, bot=None):
    """
    Точка входа после успешного парсинга / выбора исхода.
    Разделяет игроков на «опознанных» и «неопознанных», wizard для остальных.
    """
    ch_id = channel.id
    flow_lock = result_flow_locks[ch_id]
    if flow_lock.locked():
        try:
            await channel.send(
                "⚠️ Этот матч уже обрабатывается — дождись завершения или отмени лишние сообщения.",
                delete_after=20,
            )
        except Exception:
            pass
        return

    async with flow_lock:
        if ch_id in active_result_channels:
            return
        active_result_channels.add(ch_id)
        try:
            await _start_result_flow_locked(channel, host, guild, parsed, match_data, bot)
        except Exception:
            active_result_channels.discard(ch_id)
            wizard_sessions.pop(ch_id, None)
            raise


def _normalize_host_relative_teams(parsed: dict, host, match_data: dict) -> dict:
    if not parsed.get("teams_relative_to_host"):
        return parsed

    host_id = getattr(host, "id", None)
    team1_ids = set(match_data.get("team1_ids", []))
    team2_ids = set(match_data.get("team2_ids", []))
    team1_side = match_data.get("team1_side", "attack")
    team2_side = "defense" if team1_side == "attack" else "attack"

    if host_id in team1_ids:
        ally_side, enemy_side = team1_side, team2_side
    elif host_id in team2_ids:
        ally_side, enemy_side = team2_side, team1_side
    else:
        return parsed

    side_map = {"attack": ally_side, "defense": enemy_side}
    normalized = dict(parsed)
    normalized["players"] = [
        {**p, "team": side_map.get(p.get("team"), p.get("team"))}
        for p in parsed.get("players", [])
    ]
    if parsed.get("winner") in side_map:
        normalized["winner"] = side_map[parsed["winner"]]
    normalized["teams_relative_to_host"] = False
    return normalized


def _infer_winner_team(parsed: dict, host, match_data: dict) -> int | None:
    enriched = dict(parsed)
    host_id = getattr(host, "id", None)
    if enriched.get("host_id") is None and host_id is not None:
        enriched["host_id"] = host_id
    if enriched.get("host_team") is None and host_id is not None:
        if host_id in set(match_data.get("team1_ids", [])):
            enriched["host_team"] = 1
        elif host_id in set(match_data.get("team2_ids", [])):
            enriched["host_team"] = 2
    return guess_winner_team_from_parsed(enriched, match_data)


async def _start_result_flow_locked(channel, host, guild, parsed: dict, match_data: dict, bot=None):
    severity, roster_msg = match_roster.check_screenshot_vs_lobby(match_data, parsed)
    if severity == "block":
        await channel.send(
            embed=ui_theme.brand_embed(
                title="⚠️  Состав не сходится",
                description=roster_msg,
                color=ui_theme.COLOR_DANGER,
            ),
        )
        return

    parsed = _normalize_host_relative_teams(parsed, host, match_data)
    inferred_team = _infer_winner_team(parsed, host, match_data)
    if inferred_team in (1, 2):
        parsed["winner_team"] = inferred_team
    players_raw: list[dict] = parsed.get("players", [])
    team1_ids = match_data.get("team1_ids", [])
    team2_ids = match_data.get("team2_ids", [])
    all_ids = team1_ids + team2_ids

    linked = db_manager.get_players_bulk(all_ids)
    auto_matched: dict[int, dict] = screenshot_parser.match_players_to_discord(players_raw, linked)

    host_won = parsed.get("host_won")
    host_id = getattr(host, "id", None)
    if host_won is not None and host_id is not None and host_id in auto_matched:
        host_team = auto_matched[host_id].get("team")
        other_team = "defense" if host_team == "attack" else "attack"
        parsed["winner"] = host_team if host_won else other_team

    unmatched_discord_ids = [uid for uid in all_ids if uid not in auto_matched]

    already_matched_riot_ids = set()
    for uid, entry in linked.items():
        riot_key = f"{entry.get('riot_name','').lower()}#{entry.get('riot_tag','').lower()}"
        already_matched_riot_ids.add(riot_key)
        already_matched_riot_ids.add(entry.get("riot_name", "").lower())

    unmatched_nicks = []
    for p in players_raw:
        riot_id = (p.get("riot_id") or "").strip()
        riot_key = riot_id.lower()
        name_only = riot_key.split("#")[0]
        if riot_key not in already_matched_riot_ids and name_only not in already_matched_riot_ids:
            unmatched_nicks.append({
                "riot_id": riot_id,
                "stats": {
                    "team": p.get("team"),
                    "kills": p.get("kills", 0) or 0,
                    "deaths": p.get("deaths", 0) or 0,
                    "assists": p.get("assists", 0) or 0,
                    "acs": p.get("acs", 0) or 0,
                    "hs_percent": p.get("hs_percent"),
                },
            })

    if not unmatched_discord_ids:
        await _finalize_match(
            channel=channel,
            parsed=parsed,
            match_data=match_data,
            matched_stats=auto_matched,
            linked=linked,
        )
    else:
        await _matching_wizard(
            channel=channel,
            host=host,
            guild=guild,
            unmatched_discord_ids=unmatched_discord_ids,
            unmatched_nicks=unmatched_nicks,
            already_matched=auto_matched,
            parsed=parsed,
            match_data=match_data,
            linked=linked,
            bot=bot,
        )


async def _matching_wizard(
    channel, host, guild,
    unmatched_discord_ids: list,
    unmatched_nicks: list,
    already_matched: dict, parsed: dict, match_data: dict, linked: dict,
    bot=None,
):
    matched_stats = dict(already_matched)
    available_nicks = list(unmatched_nicks)
    total = len(unmatched_discord_ids)
    inter_bot = bot
    session = str(uuid.uuid4())
    wizard_sessions[channel.id] = session

    def _alive() -> bool:
        return wizard_sessions.get(channel.id) == session

    async def process_next(idx: int):
        if not _alive():
            return
        if idx >= total:
            await _finalize_match(
                channel=channel,
                parsed=parsed,
                match_data=match_data,
                matched_stats=matched_stats,
                linked=linked,
            )
            return

        discord_id = unmatched_discord_ids[idx]
        member = guild.get_member(discord_id)
        name = member.display_name if member else str(discord_id)
        remaining = total - idx

        embed = disnake.Embed(
            title=f"👤 Кто на скрине — это **{name}**?",
            description=(
                f"Участник не привязан через `/link`.\n"
                f"**{host.mention}**, выбери ник с скриншота или пропусти.\n\n"
                f"Осталось: {remaining} из {total}"
            ),
            color=disnake.Color.blurple(),
        )

        view = PickNickView(
            host=host,
            discord_id=discord_id,
            available_nicks=available_nicks,
            wizard_session=session,
            channel_id=channel.id,
            on_pick=lambda riot_id, stats: on_picked(discord_id, riot_id, stats, idx),
            on_skip=lambda: on_skipped(idx),
        )
        msg = await channel.send(embed=embed, view=view)
        result_flow_cleanup.track(channel.id, msg)

    async def on_picked(discord_id: int, riot_id: str, stats: dict, idx: int):
        if not _alive():
            return
        matched_stats[discord_id] = stats
        for i, n in enumerate(available_nicks):
            if (n.get("riot_id") or "").strip() == riot_id.strip():
                available_nicks.pop(i)
                break

        name, tag = _split_riot_id(riot_id)
        existing = db_manager.get_player(discord_id)
        if existing is None:
            asyncio.create_task(_auto_link_with_rank(discord_id, name, tag, bot=inter_bot))
        elif existing.get("riot_name", "").lower() != name.lower():
            asyncio.create_task(_auto_link_with_rank(discord_id, name, tag, bot=inter_bot))

        await process_next(idx + 1)

    async def on_skipped(idx: int):
        if not _alive():
            return
        await process_next(idx + 1)

    await process_next(0)


def _split_riot_id(riot_id: str) -> tuple[str, str]:
    if "#" in riot_id:
        parts = riot_id.split("#", 1)
        return parts[0].strip(), parts[1].strip()
    return riot_id.strip(), "???"


async def _auto_link_with_rank(discord_id: int, name: str, tag: str, bot=None):
    try:
        rank_data = await riot_api.get_player_rank(name, tag)
        if rank_data:
            db_manager.link_player(
                discord_id=discord_id,
                riot_name=name,
                riot_tag=tag,
                region="eu",
                rank=rank_data["rank"],
                rank_weight=rank_data["weight"],
                elo=rank_data["elo"],
            )
            log.info(f"Автопривязка {name}#{tag} → discord_id={discord_id}, ранг={rank_data['rank']}")
        else:
            db_manager.link_player(
                discord_id=discord_id,
                riot_name=name,
                riot_tag=tag,
                region="eu",
                rank="Unrated",
                rank_weight=0,
                elo=0,
            )
            log.info(f"Автопривязка {name}#{tag} → discord_id={discord_id} (ранг не получен)")

        if bot:
            await _send_link_confirmation_dm(bot, discord_id, name, tag, rank_data)

    except Exception as e:
        log.warning(f"_auto_link_with_rank failed: {e}")


async def _send_link_confirmation_dm(bot, discord_id: int, name: str, tag: str, rank_data: dict | None):
    try:
        user = bot.get_user(discord_id) or await bot.fetch_user(discord_id)
        if user is None:
            return

        rank_str = ""
        if rank_data:
            emoji = riot_api.rank_emoji(rank_data["rank"])
            rank_str = f"\nРанг: {emoji} **{rank_data['rank']}** ({rank_data['rr']} RR)"

        embed = disnake.Embed(
            title="🔗 Привязка аккаунта Valorant",
            description=(
                f"Хост матча указал, что ты играл под ником:\n"
                f"## `{name}#{tag}`{rank_str}\n\n"
                f"Это твой аккаунт? Если да — он автоматически привяжется к твоему Discord.\n"
                f"Если нет — нажми **«Изменить»** и укажи правильный Riot ID."
            ),
            color=disnake.Color.blurple(),
        )
        embed.set_footer(text="Привязка нужна для подсчёта Custom ELO и балансировки команд")

        view = LinkConfirmView(discord_id=discord_id, riot_name=name, riot_tag=tag, bot=bot)
        await user.send(embed=embed, view=view)

    except disnake.Forbidden:
        log.info(f"Не удалось отправить DM пользователю {discord_id} — личные сообщения закрыты")
    except Exception as e:
        log.warning(f"_send_link_confirmation_dm failed: {e}")


async def _finalize_match(channel, parsed: dict, match_data: dict,
                          matched_stats: dict, linked: dict):
    try:
        await _finalize_match_body(channel, parsed, match_data, matched_stats, linked)
    finally:
        active_result_channels.discard(channel.id)
        wizard_sessions.pop(channel.id, None)


async def _finalize_match_body(channel, parsed: dict, match_data: dict,
                               matched_stats: dict, linked: dict):
    score_atk = parsed.get("score_attack", "?")
    score_def = parsed.get("score_defense", "?")
    players_raw = parsed.get("players", [])

    team1_ids = match_data.get("team1_ids", [])
    team2_ids = match_data.get("team2_ids", [])
    team1_side = match_data.get("team1_side", "attack")
    team2_side = "defense" if team1_side == "attack" else "attack"
    winner_side = parsed.get("winner", "?")
    winner_team = parsed.get("winner_team")

    if winner_team == 1:
        winner_ids = [uid for uid in team1_ids if uid in matched_stats]
        loser_ids = [uid for uid in team2_ids if uid in matched_stats]
        winner_label = team_label(1, match_data)
    elif winner_team == 2:
        winner_ids = [uid for uid in team2_ids if uid in matched_stats]
        loser_ids = [uid for uid in team1_ids if uid in matched_stats]
        winner_label = team_label(2, match_data)
    elif winner_side == team1_side:
        winner_ids = [uid for uid in team1_ids if uid in matched_stats]
        loser_ids = [uid for uid in team2_ids if uid in matched_stats]
        winner_label = team_label(1, match_data)
    elif winner_side == team2_side:
        winner_ids = [uid for uid in team2_ids if uid in matched_stats]
        loser_ids = [uid for uid in team1_ids if uid in matched_stats]
        winner_label = team_label(2, match_data)
    else:
        winner_ids = []
        loser_ids = list(matched_stats.keys())
        winner_label = f"Сторона: {winner_side}"

    score_winner = parsed.get("score_winner")
    score_loser = parsed.get("score_loser")
    if score_winner is None or score_loser is None:
        try:
            score_atk_int = int(score_atk) if str(score_atk).isdigit() else None
            score_def_int = int(score_def) if str(score_def).isdigit() else None
        except (ValueError, TypeError):
            score_atk_int = score_def_int = None
        if winner_team == 1 or winner_side == team1_side:
            score_winner = score_atk_int if team1_side == "attack" else score_def_int
            score_loser = score_def_int if team1_side == "attack" else score_atk_int
        elif winner_team == 2 or winner_side == team2_side:
            score_winner = score_def_int if team2_side == "defense" else score_atk_int
            score_loser = score_atk_int if team2_side == "defense" else score_def_int
        else:
            score_winner = score_loser = None

    elo_changes = {}
    if winner_ids or loser_ids:
        elo_changes = elo_engine.update_elos_after_match(
            winner_ids=winner_ids,
            loser_ids=loser_ids,
            stats_by_id=matched_stats,
            score_winner=score_winner,
            score_loser=score_loser,
        )

    all_ids = team1_ids + team2_ids
    linked_fresh = db_manager.get_players_bulk(all_ids)

    if score_winner is not None and score_loser is not None:
        sw, sl = score_winner, score_loser
    else:
        sw, sl = score_atk, score_def

    embed = ui_theme.brand_embed(
        title="🏆  Матч завершён",
        description=f"### 🥇 {winner_label}",
        color=ui_theme.COLOR_SUCCESS,
    )
    embed.add_field(
        name="Счёт",
        value=f"**{sw}**  ·  **{sl}**",
        inline=True,
    )

    sorted_players = sorted(players_raw, key=lambda p: p.get("acs", 0) or 0, reverse=True)
    perf_blocks = []
    for p in sorted_players:
        riot_id = p.get("riot_id", "?")
        k = p.get("kills", 0)
        d = p.get("deaths", 0)
        a = p.get("assists", 0)
        acs = p.get("acs", 0) or 0
        hs = p.get("hs_percent")
        is_attack = p.get("team") == "attack"
        team_icon = "🔵" if is_attack else "🔴"
        side = "Атака" if is_attack else "Защита"
        stat_line = f"{team_icon} {side} · **{acs}** ACS · {k}/{d}/{a}"
        if hs is not None:
            stat_line += f" · HS **{hs}%**"
        perf_blocks.append(f"**{riot_id}**\n-# {stat_line}")

    if perf_blocks:
        embed.add_field(
            name="📋  Статистика",
            value="\n\n".join(perf_blocks),
            inline=False,
        )

    elo_blocks = []
    for uid, ch in elo_changes.items():
        entry = linked_fresh.get(uid) or linked.get(uid) or {}
        rn, rt = entry.get("riot_name"), entry.get("riot_tag")
        if rn and rt:
            name = f"{rn}#{rt}"
        elif rn:
            name = rn
        else:
            name = f"<@{uid}>"
        delta = ch["delta"]
        sign = "+" if delta >= 0 else ""
        label = elo_engine.custom_elo_to_rank_label(ch["new"])
        won = uid in winner_ids
        result = "Победа" if won else "Поражение"
        p_m = ch.get("perf_mult", 1.0)
        perf_emoji = "🔥" if p_m >= 1.2 else ("🥶" if p_m <= 0.8 else "🤝")
        elo_blocks.append(
            f"**{name}**\n"
            f"-# {result} · **{ch['old']}** → **{ch['new']}** ({sign}{delta}) · {label} · {perf_emoji} {p_m}×"
        )

    if elo_blocks:
        embed.add_field(
            name="📈  Custom ELO",
            value="\n\n".join(elo_blocks),
            inline=False,
        )

    unmatched_count = len(players_raw) - len(matched_stats)
    if unmatched_count > 0:
        embed.set_footer(
            text=f"{ui_theme.BRAND_FOOTER} · ⚠️ {unmatched_count} без /link — не в ELO"
        )

    map_name = match_data.get("map_name")
    db_manager.record_match_result(
        winner_ids=winner_ids,
        loser_ids=loser_ids,
        stats_by_id=matched_stats,
        elo_changes=elo_changes,
        map_name=map_name,
    )

    await result_flow_cleanup.cleanup_channel(channel)
    await channel.send(embed=embed)

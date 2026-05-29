"""
Профиль через Discord embed (не используется в боте).

Раньше: /profile отдавал embed с markdown-описанием.
Сейчас: /profile рендерит PNG через utils.profile_card.
"""

import disnake
from utils import riot_api, elo_engine


def _match_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "матч"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "матча"
    return "матчей"


def build_profile_embed(target: disnake.Member, data: dict, stats: dict) -> disnake.Embed:
    rank_emoji = riot_api.rank_emoji(data["rank"])
    riot_id = f"{data['riot_name']}#{data['riot_tag']}"
    updated_ts = data.get("last_updated", 0)
    custom_elo = data.get("custom_elo")
    custom_games = data.get("custom_games", 0)

    lines = [f"`{riot_id}`"]
    if updated_ts:
        lines.append(f"*Ranked · <t:{updated_ts}:R>*")

    lines.extend(["", f"{rank_emoji} **{data['rank']}**"])

    if custom_elo:
        eblot = elo_engine.custom_elo_to_rank(custom_elo)
        lines.append(
            f"{eblot['emoji']} **{eblot['name']}** · **{custom_elo}** ELO · *{custom_games} кастомок*"
        )
    else:
        lines.append("*Eblot — сыграй кастомку для калибровки*")

    if stats.get("games", 0) > 0:
        n = stats["games"]
        lines.extend([
            "",
            f"📊 **{stats['wins']}W / {stats['losses']}L** · {stats['winrate']}% WR · "
            f"последние {n} {_match_word(n)}",
            f"KD **{stats['kd']}** · KAD **{stats['kad']}** · ACS **{int(stats['avg_acs'])}**",
        ])

    embed = disnake.Embed(
        title=target.display_name,
        description="\n".join(lines),
        color=disnake.Color.blurple(),
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    return embed

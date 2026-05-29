"""
profile_cog.py — команды профиля и статистики.

Команды:
  /link <riot_id> [region]  — привязать аккаунт
  /profile [@user]          — карточка игрока с рангом и ELO
  /stats [@user] [last]     — детальная статистика по кастомкам
  /history [@user]          — последние матчи
  /rank_refresh             — обновить ранг из API
  /leaderboard              — топ по Custom ELO
  /unlink                   — отвязать аккаунт
"""

import os
import time
import logging
import disnake
from disnake.ext import commands
from disnake.ext import tasks
from utils import db_manager, riot_api, elo_engine

log = logging.getLogger(__name__)

REGIONS = ["eu", "na", "ap", "kr", "br", "latam"]


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_rank_update.start()

    def cog_unload(self):
        self.auto_rank_update.cancel()

    # ──────────────────────────────────────────────────────────────────
    # Авто-обновление рангов раз в 6 часов
    # ──────────────────────────────────────────────────────────────────
    @tasks.loop(hours=6)
    async def auto_rank_update(self):
        """Фоновая задача: обновляет ranked-ранг всех привязанных игроков."""
        all_players = db_manager.get_all_players()
        updated = 0
        for uid_str, player in all_players.items():
            if not player.get("riot_name") or player.get("riot_tag") == "???":
                continue
            try:
                rank_data = await riot_api.get_player_rank(
                    player["riot_name"], player["riot_tag"],
                    player.get("region", "eu")
                )
                if rank_data:
                    db_manager.update_rank(
                        int(uid_str),
                        rank=rank_data["rank"],
                        rank_weight=rank_data["weight"],
                        elo=rank_data["elo"],
                    )
                    updated += 1
            except Exception as e:
                log.warning(f"auto_rank_update: ошибка для {uid_str}: {e}")
        if updated:
            log.info(f"auto_rank_update: обновлено {updated} игроков")

    @auto_rank_update.before_loop
    async def before_rank_update(self):
        await self.bot.wait_until_ready()

    # ──────────────────────────────────────────────────────────────────
    # /link
    # ──────────────────────────────────────────────────────────────────
    @commands.slash_command(name="link", description="Привязать Riot-аккаунт к Discord")
    async def link(
        self,
        inter: disnake.ApplicationCommandInteraction,
        riot_id: str = commands.Param(description="Riot ID в формате Ник#TAG, например Player#EUW"),
        region: str = commands.Param(default="eu", description="Регион", choices=REGIONS),
    ):
        await inter.response.defer(ephemeral=True)

        if "#" not in riot_id:
            return await inter.edit_original_response(
                content="❌ Неверный формат. Укажи Riot ID через #, например: `Player#EUW`"
            )

        name, tag = riot_id.split("#", 1)
        name, tag = name.strip(), tag.strip()
        if not name or not tag:
            return await inter.edit_original_response(content="❌ Имя или тэг пустые.")

        await inter.edit_original_response(content=f"🔍 Ищу `{name}#{tag}` в регионе `{region}`...")
        rank_data = await riot_api.get_player_rank(name, tag, region)

        if rank_data is None:
            return await inter.edit_original_response(
                content=f"❌ Не удалось найти `{name}#{tag}` в регионе `{region}`.\n"
                        f"Проверь правильность Riot ID и регион."
            )

        db_manager.link_player(
            discord_id=inter.author.id, riot_name=name, riot_tag=tag, region=region,
            rank=rank_data["rank"], rank_weight=rank_data["weight"], elo=rank_data["elo"],
        )

        emoji = riot_api.rank_emoji(rank_data["rank"])
        embed = disnake.Embed(title="✅ Аккаунт привязан!", color=disnake.Color.green())
        embed.add_field(name="Riot ID", value=f"`{name}#{tag}`", inline=True)
        embed.add_field(name="Регион",  value=region.upper(), inline=True)
        embed.add_field(name="Ранг",    value=f"{emoji} {rank_data['rank']} ({rank_data['rr']} RR)", inline=False)
        await inter.edit_original_response(content=None, embed=embed)

    # ──────────────────────────────────────────────────────────────────
    # /profile
    # ──────────────────────────────────────────────────────────────────
    @commands.slash_command(name="profile", description="Карточка игрока")
    async def profile(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.Member = commands.Param(default=None, description="Игрок (по умолчанию — вы)"),
    ):
        await inter.response.defer()
        target = user or inter.author
        data = db_manager.get_player(target.id)

        if data is None:
            tip = "Используй `/link`." if target == inter.author else f"{target.mention} ещё не привязал аккаунт."
            return await inter.edit_original_response(content=f"❓ Аккаунт не привязан. {tip}")

        emoji = riot_api.rank_emoji(data["rank"])
        stats = db_manager.get_player_stats(target.id, last_n=20) or {}
        custom_elo   = data.get("custom_elo")
        custom_games = data.get("custom_games", 0)
        updated_ts   = data.get("last_updated", 0)

        embed = disnake.Embed(title=f"👤 {target.display_name}", color=disnake.Color.blurple())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Riot ID", value=f"`{data['riot_name']}#{data['riot_tag']}`", inline=True)
        embed.add_field(name="Регион",  value=data.get("region", "eu").upper(), inline=True)
        embed.add_field(name="Обновлено", value=f"<t:{updated_ts}:R>" if updated_ts else "—", inline=True)

        embed.add_field(
            name="Ranked ранг",
            value=f"{emoji} **{data['rank']}** ({data.get('elo', 0)} ELO)",
            inline=True,
        )

        if custom_elo:
            rank = elo_engine.custom_elo_to_rank(custom_elo)
            embed.add_field(
                name="Звание Eblot",
                value=f"**{rank['name']}** {rank['emoji']} · **{custom_elo}** ELO\n*{custom_games} кастомок*",
                inline=True,
            )
        else:
            embed.add_field(name="Звание Eblot", value="Калибровка — сыграй кастомку", inline=True)

        # Последние 20 матчей
        if stats.get("games", 0) > 0:
            embed.add_field(
                name=f"📊 Статистика (последние {stats['games']} матчей)",
                value=(
                    f"W/L: **{stats['wins']}W / {stats['losses']}L** ({stats['winrate']}% WR)\n"
                    f"K/D/A: **{stats['avg_kills']} / {stats['avg_deaths']} / {stats['avg_assists']}** "
                    f"(KD {stats['kd']})\n"
                    f"ACS: **{int(stats['avg_acs'])}** | HS: **{stats['avg_hs']}%**"
                ),
                inline=False,
            )

        await inter.edit_original_response(embed=embed)

    # ──────────────────────────────────────────────────────────────────
    # /stats
    # ──────────────────────────────────────────────────────────────────
    @commands.slash_command(name="stats", description="Детальная статистика по кастомкам")
    async def stats(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.Member = commands.Param(default=None, description="Игрок"),
        last: int = commands.Param(default=20, description="Количество последних матчей", ge=1, le=100),
    ):
        await inter.response.defer()
        target = user or inter.author
        data   = db_manager.get_player(target.id)

        if data is None:
            return await inter.edit_original_response(
                content=f"❓ {target.mention} не привязал аккаунт (`/link`)."
            )

        s = db_manager.get_player_stats(target.id, last_n=last)
        if not s or s.get("games", 0) == 0:
            return await inter.edit_original_response(
                content=f"📭 У {target.mention} нет матчей в истории."
            )

        custom_elo = data.get("custom_elo")
        elo_label  = elo_engine.custom_elo_to_rank_label(custom_elo) if custom_elo else "—"
        riot_rank  = riot_api.rank_emoji(data["rank"]) + " " + data["rank"]

        # Визуальная полоска W/L
        total = s["wins"] + s["losses"]
        win_blocks  = round(s["wins"]   / total * 10) if total else 0
        lose_blocks = 10 - win_blocks
        wl_bar = "🟩" * win_blocks + "🟥" * lose_blocks

        embed = disnake.Embed(
            title=f"📊 Статистика — {target.display_name}",
            color=disnake.Color.green() if s["winrate"] >= 50 else disnake.Color.red(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Riot ID",      value=f"`{data['riot_name']}#{data['riot_tag']}`", inline=True)
        embed.add_field(name="Ranked",       value=riot_rank,  inline=True)
        embed.add_field(
            name="Eblot",
            value=f"**{custom_elo}** · {elo_label}" if custom_elo else "—",
            inline=True,
        )

        embed.add_field(
            name=f"Результаты (последние {s['games']} матчей)",
            value=f"{wl_bar}\n**{s['wins']}W / {s['losses']}L** — {s['winrate']}% WR",
            inline=False,
        )
        embed.add_field(
            name="Боевые показатели",
            value=(
                f"K/D/A: **{s['avg_kills']} / {s['avg_deaths']} / {s['avg_assists']}**\n"
                f"KD Ratio: **{s['kd']}**\n"
                f"ACS (средний): **{int(s['avg_acs'])}**\n"
                f"HS%: **{s['avg_hs']}%**"
            ),
            inline=True,
        )

        # Топ матч по ACS
        history = s.get("history", [])
        if history:
            best = max(history, key=lambda m: m.get("acs", 0))
            best_ts = f"<t:{best['ts']}:d>" if best.get("ts") else "—"
            best_map = f" на **{best['map']}**" if best.get("map") else ""
            embed.add_field(
                name="🏆 Лучший матч",
                value=(
                    f"{best_ts}{best_map}\n"
                    f"ACS **{best['acs']}** | "
                    f"{best['kills']}/{best['deaths']}/{best['assists']}"
                ),
                inline=True,
            )

        await inter.edit_original_response(embed=embed)

    # ──────────────────────────────────────────────────────────────────
    # /history
    # ──────────────────────────────────────────────────────────────────
    @commands.slash_command(name="history", description="Последние матчи в кастомках")
    async def history(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.Member = commands.Param(default=None, description="Игрок"),
        count: int = commands.Param(default=10, description="Сколько матчей показать", ge=1, le=25),
    ):
        await inter.response.defer()
        target  = user or inter.author
        player  = db_manager.get_player(target.id)

        if player is None:
            return await inter.edit_original_response(
                content=f"❓ {target.mention} не привязал аккаунт (`/link`)."
            )

        history = player.get("match_history", [])[-count:][::-1]  # последние N, новые сверху

        if not history:
            return await inter.edit_original_response(
                content=f"📭 У {target.mention} нет матчей в истории."
            )

        lines = []
        for m in history:
            result_icon = "✅" if m["result"] == "win" else "❌"
            ts_str = f"<t:{m['ts']}:d>" if m.get("ts") else "—"
            k, d, a = m.get("kills",0), m.get("deaths",0), m.get("assists",0)
            acs  = m.get("acs", 0)
            delta = m.get("elo_delta", 0)
            sign  = "+" if delta >= 0 else ""
            map_str = f" | {m['map']}" if m.get("map") else ""
            lines.append(
                f"{result_icon} {ts_str}{map_str} — "
                f"{k}/{d}/{a} ACS:{acs} "
                f"({'`' + sign + str(delta) + '`'} ELO)"
            )

        embed = disnake.Embed(
            title=f"📋 История матчей — {target.display_name}",
            description="\n".join(lines),
            color=disnake.Color.blurple(),
        )
        embed.set_footer(text=f"Показано {len(history)} из {len(player.get('match_history', []))} матчей")
        await inter.edit_original_response(embed=embed)

    # ──────────────────────────────────────────────────────────────────
    # /rank_refresh
    # ──────────────────────────────────────────────────────────────────
    @commands.slash_command(name="rank_refresh", description="Обновить свой ранг из Riot API")
    async def rank_refresh(self, inter: disnake.ApplicationCommandInteraction):
        await inter.response.defer(ephemeral=True)
        data = db_manager.get_player(inter.author.id)
        if data is None:
            return await inter.edit_original_response(content="❌ Сначала привяжи аккаунт через `/link`.")

        rank_data = await riot_api.get_player_rank(data["riot_name"], data["riot_tag"], data.get("region", "eu"))
        if rank_data is None:
            return await inter.edit_original_response(content="❌ Не удалось получить данные. Попробуй позже.")

        db_manager.update_rank(inter.author.id, rank=rank_data["rank"], rank_weight=rank_data["weight"], elo=rank_data["elo"])
        emoji = riot_api.rank_emoji(rank_data["rank"])
        await inter.edit_original_response(
            content=f"✅ Ранг обновлён: {emoji} **{rank_data['rank']}** ({rank_data['rr']} RR)"
        )

    # ──────────────────────────────────────────────────────────────────
    # /leaderboard
    # ──────────────────────────────────────────────────────────────────
    @commands.slash_command(name="leaderboard", description="Топ игроков по званию Eblot")
    async def leaderboard(self, inter: disnake.ApplicationCommandInteraction):
        await inter.response.defer()
        all_players = db_manager.get_all_players()

        ranked = [
            (int(uid), d) for uid, d in all_players.items()
            if d.get("custom_elo") and d.get("custom_games", 0) > 0
        ]
        ranked.sort(key=lambda x: x[1]["custom_elo"], reverse=True)
        ranked = ranked[:15]

        if not ranked:
            return await inter.edit_original_response(
                content="📊 Пока никто не сыграл кастомок. Вперёд!"
            )

        medals = ["🥇", "🥈", "🥉"]
        lines  = []
        for i, (uid, d) in enumerate(ranked):
            medal  = medals[i] if i < 3 else f"`#{i+1}`"
            elo    = d["custom_elo"]
            rank   = elo_engine.custom_elo_to_rank(elo)
            wins   = d.get("wins", 0)
            losses = d.get("losses", 0)
            name   = d.get("riot_name") or f"<@{uid}>"
            lines.append(f"{medal} **{name}** — {rank['emoji']} **{rank['name']}** · {elo} | {wins}W/{losses}L")

        embed = disnake.Embed(
            title="🏆 Eblot Leaderboard",
            description="\n".join(lines),
            color=disnake.Color.gold(),
        )
        embed.set_footer(text="Звания Eblot — отдельная лadder кастомок, не Ranked Valorant")
        await inter.edit_original_response(embed=embed)

    # ──────────────────────────────────────────────────────────────────
    # /unlink
    # ──────────────────────────────────────────────────────────────────
    @commands.slash_command(name="unlink", description="Отвязать Riot-аккаунт")
    async def unlink(self, inter: disnake.ApplicationCommandInteraction):
        await inter.response.defer(ephemeral=True)
        import json
        db_path = db_manager.DB_PATH
        if os.path.exists(db_path):
            with open(db_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            key = str(inter.author.id)
            if key in raw.get("players", {}):
                del raw["players"][key]
                with open(db_path, "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
                return await inter.edit_original_response(content="✅ Аккаунт отвязан.")
        await inter.edit_original_response(content="❌ У тебя нет привязанного аккаунта.")



def setup(bot):
    bot.add_cog(Profile(bot))

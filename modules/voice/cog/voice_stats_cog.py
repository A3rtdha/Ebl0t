"""Сервер: /voice_stats и /voice_top."""

import logging
import disnake
from disnake.ext import commands, tasks
from modules.voice.storage import voice_time
from shared import ui_theme

log = logging.getLogger(__name__)


class VoiceStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._flush_voice_time.start()

    def cog_unload(self):
        self._flush_voice_time.cancel()
        voice_time.flush_active_sessions()

    @tasks.loop(minutes=2)
    async def _flush_voice_time(self):
        voice_time.flush_active_sessions()

    @_flush_voice_time.before_loop
    async def _flush_before(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        voice_time.load_persisted_active(self.bot)
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue
                if member.voice and member.voice.channel:
                    voice_time.start_session(guild.id, member.id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: disnake.Member,
        before: disnake.VoiceState,
        after: disnake.VoiceState,
    ):
        if member.bot or not member.guild:
            return

        gid, uid = member.guild.id, member.id
        if before.channel and before.channel != after.channel:
            voice_time.end_session(gid, uid)

        if after.channel and before.channel != after.channel:
            voice_time.start_session(gid, uid)

    @commands.slash_command(name="voice_stats", description="Сколько времени в голосовых на сервере")
    async def voice_stats(
        self,
        inter: disnake.ApplicationCommandInteraction,
        user: disnake.Member = commands.Param(default=None, description="Кого посмотреть"),
    ):
        target = user or inter.author
        seconds = voice_time.get_total_seconds(inter.guild.id, target.id)
        embed = ui_theme.brand_embed(
            title="🎧  Голосовая активность",
            description=(
                f"{target.mention} на **{inter.guild.name}**\n"
                f"{ui_theme.DIVIDER}\n"
                f"**{voice_time.format_duration(seconds)}** в голосовых каналах"
            ),
            color=ui_theme.COLOR_PRIMARY,
        )
        await inter.response.send_message(embed=embed, ephemeral=True)

    @commands.slash_command(name="voice_top", description="Топ по времени в голосовых на сервере")
    async def voice_top(
        self,
        inter: disnake.ApplicationCommandInteraction,
        limit: int = commands.Param(default=15, ge=5, le=25, description="Сколько мест"),
    ):
        await inter.response.defer()
        rows = voice_time.get_guild_leaderboard(inter.guild.id, limit=limit)
        if not rows:
            return await inter.edit_original_response(
                content="Пока нет данных — зайди в любой голосовой канал на сервере."
            )

        lines = []
        for i, (uid, sec) in enumerate(rows, 1):
            member = inter.guild.get_member(uid)
            name = member.display_name if member else f"`{uid}`"
            lines.append(f"**{i}.** {name} — **{voice_time.format_duration(sec)}**")

        embed = ui_theme.brand_embed(
            title=f"🎧  Топ голосовых · {inter.guild.name}",
            description="\n".join(lines),
            color=ui_theme.COLOR_PRIMARY,
        )
        in_vc = sum(
            1
            for m in inter.guild.members
            if not m.bot and m.voice and m.voice.channel
        )
        embed.set_footer(
            text=f"{ui_theme.BRAND_FOOTER} · в ГК сейчас: {in_vc} · чекпоинт каждые 2 мин"
        )
        await inter.edit_original_response(embed=embed)


def setup(bot):
    bot.add_cog(VoiceStats(bot))

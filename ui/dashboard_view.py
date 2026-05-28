import disnake
import re
from utils import valo_logic, match_manager, db_manager
from utils import guild_setup, ui_theme
from utils.riot_api import rank_emoji

# --- ВЫБОР КАРТЫ ---
class MapSelectionView(disnake.ui.View):
    def __init__(self, host, dashboard_view, maps_list):
        super().__init__(timeout=60)
        self.host = host
        self.dashboard_view = dashboard_view
        for map_name in maps_list:
            self.add_item(MapButton(map_name))

class MapButton(disnake.ui.Button):
    def __init__(self, map_name):
        super().__init__(label=map_name, style=disnake.ButtonStyle.secondary, custom_id=f"map_{map_name}")
        self.map_name = map_name
    async def callback(self, inter):
        view = self.view
        if inter.author.id != view.host.id:
            return await inter.response.send_message("Только Хост!", ephemeral=True)
        view.dashboard_view.selected_map = self.map_name
        for child in view.dashboard_view.children:
            if child.custom_id == "dash_map":
                child.disabled = True
                child.style = disnake.ButtonStyle.gray
                child.label = f"🗺️ {self.map_name}"
        await view.dashboard_view.update_message(inter)


MAX_AGENT_REROLLS = 3  # на одного игрока за матч

# --- ГЛАВНОЕ МЕНЮ ---
class MatchDashboardView(disnake.ui.View):
    def __init__(self, host: disnake.Member, players: list, mode: str, source_channel: disnake.VoiceChannel):
        super().__init__(timeout=None)
        self.host = host
        self.players = players
        self.mode = mode
        self.source_channel = source_channel
        
        self.team1 = []
        self.team2 = []
        self.agent_assignments = {}
        self.selected_map = None
        self.reroll_counts: dict[int, int] = {}

        # Кнопка START по умолчанию выключена
        for child in self.children:
            if child.custom_id == "dash_start":
                child.disabled = True
                child.style = disnake.ButtonStyle.gray

    async def update_message(self, inter: disnake.MessageInteraction):
        is_ready = bool((self.team1 or self.team2) and self.selected_map and self.agent_assignments)

        for child in self.children:
            if child.custom_id == "dash_start":
                if is_ready:
                    child.disabled = False
                    child.style = disnake.ButtonStyle.green
                    child.label = "🚀 START MATCH"
                else:
                    child.disabled = True
                    child.style = disnake.ButtonStyle.gray
                    child.label = "⌛ WAITING SETUP..."

        embed = inter.message.embeds[0]
        embed.clear_fields()

        # Статус-строка готовности
        steps = [
            ("Команды", bool(self.team1 or self.team2)),
            ("Карта",   bool(self.selected_map)),
            ("Агенты",  bool(self.agent_assignments)),
        ]
        status_line = "  ".join(
            f"{'✅' if ok else '⬜'} {name}" for name, ok in steps
        )

        map_val = f"📍 **{self.selected_map}**" if self.selected_map else "*не выбрана*"
        embed.add_field(
            name="🗺️  Карта",
            value=map_val + f"\n{ui_theme.DIVIDER}\n{status_line}",
            inline=False,
        )

        # Подтягиваем данные о рангах одним запросом
        all_players = self.team1 + self.team2
        db_data = db_manager.get_players_bulk([m.id for m in all_players]) if all_players else {}

        def format_team(team_list):
            if not team_list:
                return "*пусто*"
            lines = []
            for member in team_list:
                agent = self.agent_assignments.get(member, None)
                entry = db_data.get(member.id)
                rank_str = ""
                if entry:
                    emoji = rank_emoji(entry["rank"])
                    rank_str = f" {emoji} `{entry['rank']}`"
                agent_str = f" — **{agent}**" if agent else ""
                lines.append(f"`▸` {member.mention}{rank_str}{agent_str}")
            avg = valo_logic.team_average_skill(team_list, db_data)
            if avg:
                lines.append(f"\n*⚖️ Средняя сила: {avg}*")
            return "\n".join(lines)

        embed.add_field(
            name=f"🔵  Атака · {len(self.team1)}",
            value=format_team(self.team1),
            inline=True,
        )
        embed.add_field(
            name=f"🔴  Защита · {len(self.team2)}",
            value=format_team(self.team2),
            inline=True,
        )

        embed.color = ui_theme.COLOR_SUCCESS if is_ready else ui_theme.COLOR_PRIMARY
        if not (embed.footer and embed.footer.text):
            embed.set_footer(text=ui_theme.BRAND_FOOTER)

        await inter.response.edit_message(embed=embed, view=self)

    # --- КНОПКИ ---
    @disnake.ui.button(label="👥 TEAM", style=disnake.ButtonStyle.blurple, custom_id="dash_team", row=0)
    async def team_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост!", ephemeral=True)
        self.team1, self.team2 = valo_logic.split_teams(self.players)
        button.disabled = True
        button.style = disnake.ButtonStyle.gray
        await self.update_message(inter)

    @disnake.ui.button(label="🗺️ MAP", style=disnake.ButtonStyle.blurple, custom_id="dash_map", row=0)
    async def map_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост!", ephemeral=True)
        random_maps = valo_logic.get_random_maps()
        view = MapSelectionView(self.host, self, random_maps)
        await inter.response.edit_message(view=view)

    @disnake.ui.button(label="🕵️ AGENTS", style=disnake.ButtonStyle.blurple, custom_id="dash_agents", row=0)
    async def agents_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост!", ephemeral=True)
        self.agent_assignments = valo_logic.assign_random_agents(self.players)
        button.disabled = True
        button.style = disnake.ButtonStyle.gray
        for child in self.children:
            if child.custom_id == "dash_reroll": child.disabled = False
        await self.update_message(inter)

    @disnake.ui.button(label="🔄 REROLL", style=disnake.ButtonStyle.red, custom_id="dash_reroll", disabled=True, row=1)
    async def reroll_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author not in self.players:
            return await inter.response.send_message("Вы не участвуете в матче!", ephemeral=True)
        if not self.agent_assignments:
            return await inter.response.send_message("Агенты еще не розданы!", ephemeral=True)

        used = self.reroll_counts.get(inter.author.id, 0)
        if used >= MAX_AGENT_REROLLS:
            return await inter.response.send_message(
                f"Лимит рероллов исчерпан (**{MAX_AGENT_REROLLS}** за матч).",
                ephemeral=True,
            )

        new_agent = valo_logic.get_random_agent(exclude=self.agent_assignments.get(inter.author))
        self.agent_assignments[inter.author] = new_agent
        self.reroll_counts[inter.author.id] = used + 1
        left = MAX_AGENT_REROLLS - self.reroll_counts[inter.author.id]

        await self.update_message(inter)
        await inter.followup.send(
            f"🎲 Вам выпал: **{new_agent}** (осталось рероллов: {left})",
            ephemeral=True,
        )

    @disnake.ui.button(label="⌛ WAITING SETUP...", style=disnake.ButtonStyle.gray, custom_id="dash_start", disabled=True, row=2)
    async def start_match_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только Хост может начать матч!", ephemeral=True)
        
        await inter.response.defer()
        
        lobby_id = "0000"
        if self.source_channel:
            match = re.search(r'\((\d+)\)', self.source_channel.name)
            if match: lobby_id = match.group(1)

        guild = inter.guild
        category, _, _ = await guild_setup.get_or_create_hub(guild)
        limit_t1 = len(self.team1)
        limit_t2 = len(self.team2)

        try:
            vc_team1 = await guild.create_voice_channel(name=f"🟦 Attack #{lobby_id}", category=category, user_limit=limit_t1)
            vc_team2 = await guild.create_voice_channel(name=f"🟥 Defense #{lobby_id}", category=category, user_limit=limit_t2)
        except Exception as e:
            return await inter.followup.send(f"Ошибка: {e}", ephemeral=True)

        # team1 = Attack (🟦), team2 = Defense (🟥) — по именам каналов
        match_manager.save_active_match(
            host_id=self.host.id,
            team1_channel_id=vc_team1.id,
            team2_channel_id=vc_team2.id,
            lobby_id=lobby_id,
            team1_ids=self.team1,
            team2_ids=self.team2,
            team1_side="attack",
        )

        async def move_player(member, channel):
            try:
                if member.voice: await member.move_to(channel)
            except: pass

        for m in self.team1: await move_player(m, vc_team1)
        for m in self.team2: await move_player(m, vc_team2)

        try:
            if self.source_channel: await self.source_channel.delete()
        except: pass

        embed = inter.message.embeds[0]
        embed.title = f"🚀  Матч #{lobby_id} запущен!"
        embed.color = ui_theme.COLOR_SUCCESS
        embed.clear_fields()
        embed.description = (
            f"📍 **Карта:** {self.selected_map or '—'}\n"
            f"{ui_theme.DIVIDER}\n"
            f"📢 Игроки разведены по голосовым каналам. Удачной игры!"
        )
        embed.add_field(name="🔵 Атака",  value=vc_team1.mention, inline=True)
        embed.add_field(name="🔴 Защита", value=vc_team2.mention, inline=True)
        embed.set_footer(text=f"{ui_theme.BRAND_FOOTER}  ·  /finish — завершить матч")

        for child in self.children: child.disabled = True
        
        await inter.edit_original_response(embed=embed, view=self)
        await inter.channel.send(f"{self.host.mention} — **GL & HF!** 🔥")

import disnake
import re
from utils import valo_logic, match_manager, db_manager
from utils import custom_invite, guild_setup, ui_theme

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


def _member_side(member, team1, team2) -> str:
    if member in team1:
        return "🔵 Атака"
    if member in team2:
        return "🔴 Защита"
    return "⚪ Команда не выбрана"


def _agent_card(view: "MatchDashboardView", member: disnake.Member) -> str | None:
    agent = view.agent_assignments.get(member)
    if not agent:
        return None
    left = MAX_AGENT_REROLLS - view.reroll_counts.get(member.id, 0)
    side = _member_side(member, view.team1, view.team2)
    map_line = f"📍 **{view.selected_map}**" if view.selected_map else "📍 карта не выбрана"
    return (
        f"🕵️ Твой агент: **{agent}**\n"
        f"{side} · {map_line}\n"
        f"🔄 Рероллов осталось: **{left}**"
    )


async def _dm_agent_cards(view: "MatchDashboardView", members: list) -> None:
    """ЛС при первой роздаче агентов. Реролл — только ephemeral."""
    for member in members:
        text = _agent_card(view, member)
        if not text:
            continue
        try:
            await member.send(text)
        except (disnake.Forbidden, disnake.HTTPException):
            pass


# --- ГЛАВНОЕ МЕНЮ ---
class MatchDashboardView(disnake.ui.View):
    def __init__(
        self,
        host: disnake.Member,
        players: list,
        mode: str,
        source_channel: disnake.VoiceChannel,
        *,
        dev_mode: bool = False,
    ):
        super().__init__(timeout=None)
        self.host = host
        self.players = players
        self.mode = mode
        self.source_channel = source_channel
        self.dev_mode = dev_mode
        
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

    def _enable_agent_buttons(self) -> None:
        for child in self.children:
            if child.custom_id in ("dash_reroll", "dash_my_agent"):
                child.disabled = False

    def build_embed(self) -> disnake.Embed:
        is_ready = bool((self.team1 or self.team2) and self.selected_map and self.agent_assignments)
        steps = [
            ("Команды", bool(self.team1 or self.team2)),
            ("Карта", bool(self.selected_map)),
            ("Агенты", bool(self.agent_assignments)),
        ]
        status_line = "  ".join(f"{'✅' if ok else '⬜'} {name}" for name, ok in steps)
        map_val = f"**{self.selected_map}**" if self.selected_map else "*не выбрана*"

        all_players = self.team1 + self.team2
        db_data = db_manager.get_players_bulk([m.id for m in all_players]) if all_players else {}

        def format_team(team_list):
            if not team_list:
                return "—"
            blocks = []
            for member in team_list:
                skill = valo_logic.player_skill_elo(member, db_data)
                agent = self.agent_assignments.get(member)
                sub_line = f"ELO **{skill}**"
                if agent:
                    sub_line += f" · 🕵️ **{agent}**"
                blocks.append(f"{member.mention}\n-# {sub_line}")
            body = "\n\n".join(blocks)
            avg = valo_logic.team_average_skill(team_list, db_data)
            if avg:
                body += f"\n\n{ui_theme.DIVIDER}\n-# ⚖️ Средняя команды: **{avg}**"
            return body

        desc = (
            f"**Хост:** {self.host.mention}\n"
            f"📍 Карта: {map_val}  ·  {status_line}"
        )
        if self.dev_mode:
            desc += f"\n{ui_theme.DIVIDER}\n-# 🔧 DEV · завершение: **`/finish`** в этом канале"

        embed = ui_theme.brand_embed(
            title=f"⚔️  Настройка матча · {self.mode}",
            description=desc,
            color=ui_theme.COLOR_SUCCESS if is_ready else ui_theme.COLOR_PRIMARY,
        )
        embed.add_field(name=f"🔵 Атака · {len(self.team1)}", value=format_team(self.team1), inline=True)
        embed.add_field(name=f"🔴 Защита · {len(self.team2)}", value=format_team(self.team2), inline=True)
        if self.agent_assignments:
            unassigned = [m for m in self.players if m not in self.agent_assignments]
            if unassigned:
                embed.add_field(
                    name="⚠️ Без агента",
                    value="\n".join(m.mention for m in unassigned),
                    inline=False,
                )
        footer = "🔧 DEV" if self.dev_mode else ui_theme.BRAND_FOOTER
        embed.set_footer(text=footer)
        return embed

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

        await inter.response.edit_message(embed=self.build_embed(), view=self)

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
        embed = ui_theme.brand_embed(
            title="🗺️  Выбор карты",
            description="Хост, нажми одну из кнопок ниже.",
            color=ui_theme.COLOR_PRIMARY,
        )
        await inter.response.edit_message(embed=embed, view=view)

    @disnake.ui.button(label="🕵️ AGENTS", style=disnake.ButtonStyle.blurple, custom_id="dash_agents", row=0)
    async def agents_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост!", ephemeral=True)
        self.agent_assignments = valo_logic.assign_random_agents(self.players)
        button.disabled = True
        button.style = disnake.ButtonStyle.gray
        self._enable_agent_buttons()
        await self.update_message(inter)
        if self.dev_mode:
            lines = [
                f"{m.display_name}: **{self.agent_assignments.get(m, '—')}**"
                for m in self.players
            ]
            await inter.followup.send(
                "🕵️ **Агенты (DEV)** — см. также в embed выше:\n" + "\n".join(lines),
                ephemeral=True,
            )
        else:
            await _dm_agent_cards(self, self.players)

    @disnake.ui.button(
        label="🕵️ Мой агент",
        style=disnake.ButtonStyle.secondary,
        custom_id="dash_my_agent",
        disabled=True,
        row=1,
    )
    async def my_agent_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author not in self.players:
            return await inter.response.send_message("Вы не участвуете в матче!", ephemeral=True)
        if not self.agent_assignments:
            return await inter.response.send_message("Агенты ещё не розданы!", ephemeral=True)

        card = _agent_card(self, inter.author)
        if not card:
            return await inter.response.send_message("Тебе агент не назначен.", ephemeral=True)
        await inter.response.send_message(card, ephemeral=True)

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

        await self.update_message(inter)
        card = _agent_card(self, inter.author)
        await inter.followup.send(card or f"🎲 **{new_agent}**", ephemeral=True)

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
            dashboard_msg_id=inter.message.id,
            text_channel_id=inter.channel.id,
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

        embed = ui_theme.brand_embed(
            title=f"🚀  Матч #{lobby_id} · {self.selected_map or '—'}",
            description=f"{self.host.mention} — **GL & HF!** 🔥",
            color=ui_theme.COLOR_SUCCESS,
        )
        embed.add_field(name="🔵 Атака", value=vc_team1.mention, inline=True)
        embed.add_field(name="🔴 Защита", value=vc_team2.mention, inline=True)
        finish_hint = "🔧 DEV · /finish" if self.dev_mode else f"{ui_theme.BRAND_FOOTER}  ·  /finish"
        embed.set_footer(text=f"{finish_hint} — завершить матч")
        await inter.edit_original_response(embed=embed, view=None)
        if not self.dev_mode:
            await custom_invite.close_for_host(guild, self.host, customs_channel=inter.channel)

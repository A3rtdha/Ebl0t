import disnake
from utils import valo_logic

# --- КНОПКИ ВЫБОРА КАРТЫ ---
class MapSelectionView(disnake.ui.View):
    def __init__(self, host, dashboard_view, maps_list):
        super().__init__(timeout=60)
        self.host = host
        self.dashboard_view = dashboard_view # Ссылка на главное меню
        self.maps_list = maps_list
        
        # Генерируем кнопки для карт
        for map_name in maps_list:
            self.add_item(MapButton(map_name))

class MapButton(disnake.ui.Button):
    def __init__(self, map_name):
        super().__init__(label=map_name, style=disnake.ButtonStyle.secondary, custom_id=f"map_{map_name}")
        self.map_name = map_name

    async def callback(self, inter: disnake.MessageInteraction):
        view: MapSelectionView = self.view
        if inter.author.id != view.host.id:
            await inter.response.send_message("Выбирать карту может только Хост!", ephemeral=True)
            return
        
        # 1. Записываем выбранную карту в главное меню
        view.dashboard_view.selected_map = self.map_name
        
        # 2. Находим кнопку MAP в главном меню и выключаем её
        for child in view.dashboard_view.children:
            if child.custom_id == "dash_map":
                child.disabled = True
                child.style = disnake.ButtonStyle.gray
                child.label = f"🗺️ {self.map_name}" # Меняем название кнопки на карту
        
        # 3. Обновляем эмбед и возвращаем главное меню
        await view.dashboard_view.update_message(inter)


# --- ГЛАВНОЕ МЕНЮ ---
class MatchDashboardView(disnake.ui.View):
    def __init__(self, host: disnake.Member, players: list, mode: str):
        super().__init__(timeout=None)
        self.host = host
        self.players = players
        self.mode = mode
        
        # Хранилище данных матча (State)
        self.team1 = []
        self.team2 = []
        self.agent_assignments = {} # Словарь {Member: "AgentName"}
        self.selected_map = None

    # Вспомогательная функция для перерисовки Эмбеда
    async def update_message(self, inter: disnake.MessageInteraction):
        # Берем старый эмбед, но очищаем поля, чтобы перезаписать их
        embed = inter.message.embeds[0]
        embed.clear_fields()

        # 1. Поле КОМАНДЫ (если они уже сформированы)
        if self.team1 or self.team2:
            t1_desc = "\n".join([m.mention for m in self.team1]) if self.team1 else "..."
            t2_desc = "\n".join([m.mention for m in self.team2]) if self.team2 else "..."
            embed.description = f"**🔵 Атака:**\n{t1_desc}\n\n**🔴 Защита:**\n{t2_desc}"
        
        # 2. Поле КАРТА (если выбрана)
        if self.selected_map:
            embed.add_field(name="🗺️ Карта", value=f"**{self.selected_map}**", inline=False)

        # 3. Поле АГЕНТЫ (если розданы)
        if self.agent_assignments:
            # Сортируем текст, чтобы он выглядел красиво (сначала команда 1, потом 2)
            lines = []
            
            # Если команды есть, делим визуально
            if self.team1:
                lines.append("**🔵 Атака:**")
                for p in self.team1:
                    agent = self.agent_assignments.get(p, "???")
                    lines.append(f"> {p.mention} — **{agent}**")
                
                lines.append("\n**🔴 Защита:**")
                for p in self.team2:
                    agent = self.agent_assignments.get(p, "???")
                    lines.append(f"> {p.mention} — **{agent}**")
            else:
                # Если команд еще нет, просто списком
                for p, agent in self.agent_assignments.items():
                    lines.append(f"{p.mention} — **{agent}**")

            full_text = "\n".join(lines)
            embed.add_field(name="🕵️ Агенты", value=full_text, inline=False)

        # Редактируем сообщение с обновленным View (кнопками)
        await inter.response.edit_message(embed=embed, view=self)


    # --- КНОПКИ ---

    @disnake.ui.button(label="👥 TEAM", style=disnake.ButtonStyle.blurple, custom_id="dash_team", row=0)
    async def team_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост!", ephemeral=True)

        # Логика
        self.team1, self.team2 = valo_logic.split_teams(self.players)
        
        # Выключаем кнопку
        button.disabled = True
        button.style = disnake.ButtonStyle.gray
        
        await self.update_message(inter)

    @disnake.ui.button(label="🗺️ MAP", style=disnake.ButtonStyle.blurple, custom_id="dash_map", row=0)
    async def map_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост!", ephemeral=True)
            
        random_maps = valo_logic.get_random_maps()
        # Передаем self (этот класс), чтобы MapSelectionView мог вернуть нас обратно
        view = MapSelectionView(self.host, self, random_maps)
        await inter.response.edit_message(view=view)

    @disnake.ui.button(label="🕵️ AGENTS", style=disnake.ButtonStyle.blurple, custom_id="dash_agents", row=0)
    async def agents_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост!", ephemeral=True)

        # Раздаем агентов
        self.agent_assignments = valo_logic.assign_random_agents(self.players)
        
        # Выключаем эту кнопку
        button.disabled = True
        button.style = disnake.ButtonStyle.gray
        
        # ВКЛЮЧАЕМ кнопку REROLL (ищем её по custom_id)
        for child in self.children:
            if child.custom_id == "dash_reroll":
                child.disabled = False
        
        await self.update_message(inter)

    # --- КНОПКА REROLL (Изначально выключена, disabled=True) ---
    @disnake.ui.button(label="🔄 REROLL AGENT", style=disnake.ButtonStyle.red, custom_id="dash_reroll", disabled=True, row=1)
    async def reroll_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        # Проверка: нажать может любой игрок, который есть в списке участников
        if inter.author not in self.players:
            return await inter.response.send_message("Вы не участвуете в этом матче!", ephemeral=True)
        
        # Если агенты еще не розданы (на всякий случай)
        if not self.agent_assignments:
             return await inter.response.send_message("Агенты еще не розданы!", ephemeral=True)

        # Выдаем нового агента конкретно нажавшему
        new_agent = valo_logic.get_random_agent()
        self.agent_assignments[inter.author] = new_agent
        
        # Обновляем эмбед
        await self.update_message(inter)
        
        # Подтверждение (эфемеричное), чтобы игрок понял, что сработало
        await inter.followup.send(f"🎲 Вам выпал новый агент: **{new_agent}**", ephemeral=True)

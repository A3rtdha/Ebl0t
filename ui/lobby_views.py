import disnake
import random
from ui.dashboard_view import MatchDashboardView # <-- Импортируем наш новый файл

CATEGORY_ID = 1275281158334185486

class WaitingRoomView(disnake.ui.View):
    def __init__(self, host: disnake.Member, voice_channel: disnake.VoiceChannel, mode: str):
        super().__init__(timeout=None)
        self.host = host
        self.voice_channel = voice_channel
        self.mode = mode

    @disnake.ui.button(label="✅ ВСЕ ГОТОВЫ", style=disnake.ButtonStyle.success, custom_id="all_ready")
    async def all_ready_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            await inter.response.send_message(f"Вы не хост, ожидайте {self.host.mention}.", ephemeral=True)
            return

        # Получаем список людей в ГК
        members_in_vc = self.voice_channel.members
        players_count = len(members_in_vc)
        
        # --- ОБХОДКА ВКЛЮЧЕНА (Для тестов) ---
        # if players_count == 0 or players_count % 2 != 0:
        #     await inter.response.send_message(
        #         f"❌ В канале **{self.voice_channel.name}** сейчас {players_count} чел.\nНужно четное количество.", 
        #         ephemeral=True
        #     )
        #     return
        # -------------------------------------

        await inter.response.defer()
        
        # Формируем список ников для красивого эмбеда
        # Если в ГК никого нет (ты тестишь без захода), берем просто тебя
        players_list_obj = members_in_vc if len(members_in_vc) > 0 else [inter.author]
        
        players_desc = "\n".join([f"• {m.mention}" for m in players_list_obj])

        # Создаем новый Эмбед (Dashboard)
        embed = disnake.Embed(
            title=f"⚔️ Матч | Режим: {self.mode}",
            description=f"**Игроки ({len(players_list_obj)}):**\n{players_desc}\n\nНастройте матч кнопками ниже:",
            color=disnake.Color.blurple()
        )
        
        # Переключаем View на новый (из файла dashboard_view.py)
        view = MatchDashboardView(host=self.host, players=players_list_obj, mode=self.mode)

        # Редактируем сообщение
        await inter.edit_original_response(embed=embed, view=view)


class SetupModeView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def create_lobby(self, inter: disnake.MessageInteraction, mode_name: str):
        await inter.response.defer()
        guild = inter.guild
        category = guild.get_channel(CATEGORY_ID)
        
        lobby_num = random.randint(1000, 9999)
        vc_name = f"Ожидание ({lobby_num})"
        
        try:
            vc = await guild.create_voice_channel(name=vc_name, category=category)
        except disnake.errors.Forbidden:
            await inter.edit_original_response(content="❌ Нет прав создавать каналы!")
            return

        embed = disnake.Embed(
            title=f"⏳ Ожидание игроков | Режим: {mode_name}",
            description=(
                f"**Организатор:** {inter.author.mention}\n"
                f"**Голосовой канал:** {vc.mention}\n\n"
                f"> Ждем игроков..."
            ),
            color=disnake.Color.orange()
        )

        view = WaitingRoomView(host=inter.author, voice_channel=vc, mode=mode_name)
        await inter.edit_original_response(embed=embed, view=view)

    @disnake.ui.button(label="🎲 RANDOM", style=disnake.ButtonStyle.blurple, custom_id="mode_random")
    async def random_mode(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self.create_lobby(inter, "RANDOM")

    @disnake.ui.button(label="🏆 VOTED", style=disnake.ButtonStyle.green, custom_id="mode_voted")
    async def voted_mode(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self.create_lobby(inter, "VOTED")

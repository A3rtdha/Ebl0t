import disnake
import random
import asyncio
import logging
from ui.dashboard_view import MatchDashboardView
from utils import guild_setup, db_manager, riot_api, custom_invite
from utils import ui_theme

log = logging.getLogger(__name__)


async def _sync_lobby_ranks(players: list):
    """Фоновая сверка актуальности рангов лобби (троттлинг внутри riot_api)."""
    try:
        ids = [m.id for m in players]
        linked = db_manager.get_players_bulk(ids)
        if not linked:
            return

        def _apply(uid, rd):
            db_manager.update_rank(uid, rd["rank"], rd["weight"], rd["elo"])

        await riot_api.refresh_ranks_bulk(linked, on_update=_apply)
    except Exception as e:
        log.warning(f"Сверка рангов лобби не удалась: {e}")

class WaitingRoomView(disnake.ui.View):
    def __init__(
        self,
        host: disnake.Member,
        voice_channel: disnake.VoiceChannel,
        mode: str,
        *,
        dev_mode: bool = False,
    ):
        super().__init__(timeout=None)
        self.host = host
        self.voice_channel = voice_channel
        self.mode = mode
        self.dev_mode = dev_mode

    @disnake.ui.button(label="✅ ВСЕ ГОТОВЫ", style=disnake.ButtonStyle.success, custom_id="all_ready")
    async def all_ready_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            await inter.response.send_message(f"Вы не хост, ожидайте {self.host.mention}.", ephemeral=True)
            return

        vc = inter.guild.get_channel(self.voice_channel.id)
        if not isinstance(vc, disnake.VoiceChannel):
            return await inter.response.send_message(
                "❌ Голосовой канал ожидания не найден (удалён?). Создай лобби заново через `/custom`.",
                ephemeral=True,
            )
        members_in_vc = vc.members

        # --- ВАЛИДАЦИЯ (Для тестов отключена) ---
        # players_count = len(members_in_vc)
        # if players_count == 0 or players_count % 2 != 0:
        #     return await inter.response.send_message("Нечетное кол-во игроков!", ephemeral=True)
        # ----------------------------------------

        await inter.response.defer()
        
        # Если в ГК пусто (тест), берем хоста
        players_list_obj = members_in_vc if len(members_in_vc) > 0 else [inter.author]

        # Автоматически сверяем ранги в фоне, пока хост настраивает матч
        asyncio.create_task(_sync_lobby_ranks(list(players_list_obj)))

        view = MatchDashboardView(
            host=self.host,
            players=players_list_obj,
            mode=self.mode,
            source_channel=self.voice_channel,
            dev_mode=self.dev_mode,
        )

        await inter.edit_original_response(embed=view.build_embed(), view=view)


class SetupModeView(disnake.ui.View):
    def __init__(self, *, dev_mode: bool = False):
        super().__init__(timeout=None)
        self.dev_mode = dev_mode

    async def create_lobby(self, inter: disnake.MessageInteraction, mode_name: str):
        await inter.response.defer()
        category, _, _ = await guild_setup.get_or_create_hub(inter.guild)
        
        lobby_num = random.randint(1000, 9999)
        vc_name = f"Ожидание ({lobby_num})"
        
        try:
            vc = await inter.guild.create_voice_channel(name=vc_name, category=category)
        except disnake.errors.Forbidden:
            await inter.edit_original_response(content="❌ Нет прав создавать каналы!")
            return

        embed = custom_invite.lobby_gather_embed(
            inter.author, vc, mode_name, dev_mode=self.dev_mode,
        )

        view = WaitingRoomView(
            host=inter.author, voice_channel=vc, mode=mode_name, dev_mode=self.dev_mode,
        )
        await inter.edit_original_response(embed=embed, view=view)

        if not self.dev_mode:
            role = await guild_setup.get_or_create_valorant_role(inter.guild)
            await custom_invite.post_gather_announcement(
                inter.guild, inter.author, vc, mode_name, ping_role=role,
            )

    @disnake.ui.button(label="🎲 RANDOM", style=disnake.ButtonStyle.blurple, custom_id="mode_random")
    async def random_mode(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self.create_lobby(inter, "RANDOM")

    @disnake.ui.button(label="🏆 VOTED", style=disnake.ButtonStyle.green, custom_id="mode_voted")
    async def voted_mode(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self.create_lobby(inter, "VOTED")

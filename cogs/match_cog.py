"""
match_cog.py — завершение матча и обработка результатов.

Полный флоу:
1. Хост вызывает /finish
2. Бот удаляет ГК команд, сохраняет match_data в ScreenshotListener
3. Хост прикрепляет скриншот scoreboard-а в чат
4. Бот парсит скриншот через Claude Vision (K/D/A, ACS, победитель)
5. Игроки, у которых есть /link — матчатся автоматически по Riot ID
6. Участники кастомки без /link — по одному сообщению: «Кто на скрине — это @Name?»
   Выпадающий список = ники с скрина. Левые ники (не из кастомки) не спрашиваем.
7. После сопоставления всех (или пропуска) — Riot ID автоматически
   сохраняется в БД (как /link без ранга), ELO обновляется, публикуется
   финальный embed.
"""

import disnake
from disnake.ext import commands
from utils import match_manager, db_manager, elo_engine, screenshot_parser, riot_api
from ui.modals import MatchResultModal
import asyncio
import logging

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# /finish — точка входа
# ══════════════════════════════════════════════════════════════════════

class MatchCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name="finish", description="Завершить матч и загрузить скриншот результатов")
    async def finish_match(self, inter: disnake.ApplicationCommandInteraction):
        match_data = match_manager.get_active_match(inter.author.id)
        if not match_data:
            # Ищем — вдруг этот юзер участник матча, но не хост
            all_matches = match_manager.get_all_active_matches()
            for host_id_str, md in all_matches.items():
                if inter.author.id in md.get("team1_ids", []) + md.get("team2_ids", []):
                    return await inter.response.send_message(
                        f"❌ Ты участник матча, но не хост. "
                        f"Попроси хоста (<@{md['host_id']}>) завершить матч командой `/finish`.",
                        ephemeral=True,
                    )
            return await inter.response.send_message("❌ Нет активного матча.", ephemeral=True)

        # Удаляем голосовые каналы
        for ch_id in [match_data.get("team1_vc"), match_data.get("team2_vc")]:
            if ch_id:
                ch = inter.guild.get_channel(ch_id)
                if ch:
                    try:
                        await ch.delete()
                    except Exception:
                        pass

        match_manager.remove_active_match(inter.author.id)

        # Регистрируем ожидание скриншота
        listener: ScreenshotListener = self.bot.get_cog("ScreenshotListener")
        if listener:
            listener.register(
                channel_id=inter.channel.id,
                host_id=inter.author.id,
                match_data=match_data,
                guild=inter.guild,
            )

        embed = disnake.Embed(
            title="📸 Загрузи скриншот результатов",
            description=(
                "Прикрепи **скриншот таблицы результатов** (scoreboard) из Valorant "
                "к следующему сообщению в этом чате.\n\n"
                "Бот автоматически распознает победителя, счёт и статистику игроков, "
                "а затем обновит Custom ELO всех участников.\n\n"
                "Если игрок не привязал `/link` — бот спросит хоста, кто есть кто.\n\n"
                "Или нажми **«Ввести вручную»**, если скриншота нет."
            ),
            color=disnake.Color.orange(),
        )
        view = ManualFallbackView(host=inter.author, channel=inter.channel)
        await inter.response.send_message(embed=embed, view=view)


# ══════════════════════════════════════════════════════════════════════
# Кнопка «Ввести вручную» — fallback
# ══════════════════════════════════════════════════════════════════════

class ManualFallbackView(disnake.ui.View):
    def __init__(self, host: disnake.Member, channel):
        super().__init__(timeout=300)
        self.host = host
        self.channel = channel

    @disnake.ui.button(label="✏️ Ввести вручную", style=disnake.ButtonStyle.secondary)
    async def manual_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост может завершить матч.", ephemeral=True)
        # Снимаем регистрацию ожидания скриншота
        listener = inter.bot.get_cog("ScreenshotListener")
        if listener:
            listener.unregister(inter.channel.id)
        self.stop()
        await inter.response.send_modal(modal=MatchResultModal(inter.bot, self.channel))


# ══════════════════════════════════════════════════════════════════════
# Listener — ждёт скриншот в чате от хоста
# ══════════════════════════════════════════════════════════════════════

class ScreenshotListener(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # {channel_id: {"host_id": int, "match_data": dict, "guild": Guild}}
        self.pending: dict[int, dict] = {}

    def register(self, channel_id: int, host_id: int, match_data: dict, guild):
        self.pending[channel_id] = {
            "host_id":    host_id,
            "match_data": match_data,
            "guild":      guild,
        }

    def unregister(self, channel_id: int):
        self.pending.pop(channel_id, None)

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        if message.author.bot:
            return

        pending = self.pending.get(message.channel.id)
        if not pending or message.author.id != pending["host_id"]:
            return

        # Ищем изображение среди вложений
        image_att = next(
            (a for a in message.attachments if a.content_type and a.content_type.startswith("image/")),
            None,
        )
        if image_att is None:
            return

        # Регистрацию снимаем сразу — один скриншот, один раз
        self.unregister(message.channel.id)

        status = await message.channel.send("🔍 Анализирую скриншот... подожди несколько секунд.")

        try:
            image_bytes  = await image_att.read()
            content_type = image_att.content_type or "image/png"
            parsed       = await screenshot_parser.parse_screenshot(image_bytes, content_type)

            if parsed is None:
                return await status.edit(content=(
                    "❌ Не удалось распознать скриншот.\n"
                    "Убедись, что это **экран результатов Valorant** (scoreboard после матча).\n"
                    "Если нужно — введи результат вручную через `/finish`."
                ))

            await status.delete()
            await _start_result_flow(
                channel=message.channel,
                host=message.author,
                guild=pending["guild"],
                parsed=parsed,
                match_data=pending["match_data"],
                bot=self.bot,
            )

        except Exception as e:
            log.exception("Ошибка при обработке скриншота")
            await status.edit(content=f"❌ Внутренняя ошибка: `{e}`")


# ══════════════════════════════════════════════════════════════════════
# Флоу обработки результатов
# ══════════════════════════════════════════════════════════════════════

async def _start_result_flow(channel, host, guild, parsed: dict, match_data: dict, bot=None):
    """
    Точка входа после успешного парсинга.
    Разделяет игроков на «опознанных» и «неопознанных»,
    запускает поочерёдный dropdown для неопознанных.
    """
    players_raw: list[dict] = parsed.get("players", [])
    team1_ids   = match_data.get("team1_ids", [])
    team2_ids   = match_data.get("team2_ids", [])
    all_ids     = team1_ids + team2_ids

    # Все участники матча из БД
    linked = db_manager.get_players_bulk(all_ids)

    # Автоматическое сопоставление по Riot ID
    auto_matched: dict[int, dict] = screenshot_parser.match_players_to_discord(players_raw, linked)

    # Победитель относительно хоста: смотрим надпись «Победа»/«Поражение» и команду хоста
    host_won = parsed.get("host_won")
    host_id = getattr(host, "id", None)
    if host_won is not None and host_id is not None and host_id in auto_matched:
        host_team = auto_matched[host_id].get("team")
        other_team = "defense" if host_team == "attack" else "attack"
        parsed["winner"] = host_team if host_won else other_team

    # Участники кастомки без привязки к нику (им нужно выбрать ник с скрина)
    unmatched_discord_ids = [uid for uid in all_ids if uid not in auto_matched]

    # Ники с скрина, которые ещё не привязаны ни к кому (кандидаты для выбора)
    already_matched_riot_ids = set()
    for uid, entry in linked.items():
        riot_key = f"{entry.get('riot_name','').lower()}#{entry.get('riot_tag','').lower()}"
        already_matched_riot_ids.add(riot_key)
        already_matched_riot_ids.add(entry.get("riot_name","").lower())

    unmatched_nicks = []  # [{"riot_id": str, "stats": dict}, ...]
    for p in players_raw:
        riot_id = (p.get("riot_id") or "").strip()
        riot_key = riot_id.lower()
        name_only = riot_key.split("#")[0]
        if riot_key not in already_matched_riot_ids and name_only not in already_matched_riot_ids:
            unmatched_nicks.append({
                "riot_id": riot_id,
                "stats": {
                    "team":       p.get("team"),
                    "kills":      p.get("kills", 0) or 0,
                    "deaths":     p.get("deaths", 0) or 0,
                    "assists":    p.get("assists", 0) or 0,
                    "acs":        p.get("acs", 0) or 0,
                    "hs_percent": p.get("hs_percent"),
                },
            })

    if not unmatched_discord_ids:
        # Все участники кастомки уже определены — левые ники на скрине просто не добавляем
        await _finalize_match(
            channel=channel,
            parsed=parsed,
            match_data=match_data,
            matched_stats=auto_matched,
            linked=linked,
        )
    else:
        # Один запрос на каждого участника без привязки: "Кто на скрине — это @Name?" → выбор ника
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
    """
    Один запрос на каждого участника кастомки без привязки:
    «Кто на скрине — это @Name?» → выбор ника из выпадающего списка.
    Левые ники на скрине не добавляем — только сопоставляем участников.
    """
    matched_stats = dict(already_matched)
    # Копия списка ников: при выборе убираем, чтобы не предлагать повторно
    available_nicks = list(unmatched_nicks)
    total = len(unmatched_discord_ids)
    inter_bot = bot

    async def process_next(idx: int):
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
            on_pick=lambda riot_id, stats: on_picked(discord_id, riot_id, stats, idx),
            on_skip=lambda: on_skipped(idx),
        )
        await channel.send(embed=embed, view=view)

    async def on_picked(discord_id: int, riot_id: str, stats: dict, idx: int):
        matched_stats[discord_id] = stats
        # Убираем выбранный ник из списка для следующих
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
        await process_next(idx + 1)

    await process_next(0)


def _split_riot_id(riot_id: str) -> tuple[str, str]:
    """Разбивает 'Name#TAG' на ('Name', 'TAG'). Если нет # — TAG='???'."""
    if "#" in riot_id:
        parts = riot_id.split("#", 1)
        return parts[0].strip(), parts[1].strip()
    return riot_id.strip(), "???"


async def _auto_link_with_rank(discord_id: int, name: str, tag: str, bot=None):
    """
    Фоновая задача: получает ранг через Henrik API, сохраняет /link,
    затем отправляет игроку DM с просьбой подтвердить привязку.
    """
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

        # Отправляем DM игроку с запросом подтверждения
        if bot:
            await _send_link_confirmation_dm(bot, discord_id, name, tag, rank_data)

    except Exception as e:
        log.warning(f"_auto_link_with_rank failed: {e}")


async def _send_link_confirmation_dm(bot, discord_id: int, name: str, tag: str, rank_data: dict | None):
    """Отправляет личное сообщение игроку с просьбой подтвердить Riot ID."""
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


# ══════════════════════════════════════════════════════════════════════
# View подтверждения в DM
# ══════════════════════════════════════════════════════════════════════

class LinkConfirmView(disnake.ui.View):
    """
    Кнопки «✅ Да, всё верно» и «✏️ Изменить» в личных сообщениях игрока.
    """
    def __init__(self, discord_id: int, riot_name: str, riot_tag: str, bot):
        super().__init__(timeout=86400)  # 24 часа
        self.discord_id = discord_id
        self.riot_name  = riot_name
        self.riot_tag   = riot_tag
        self.bot        = bot

    @disnake.ui.button(label="✅ Да, это я", style=disnake.ButtonStyle.green)
    async def confirm_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        self.stop()
        # Привязка уже сохранена — просто подтверждаем
        for child in self.children:
            child.disabled = True
        await inter.response.edit_message(
            content="✅ Отлично! Аккаунт подтверждён. Теперь в следующих матчах ты будешь распознаваться автоматически.",
            embed=None,
            view=self,
        )

    @disnake.ui.button(label="✏️ Изменить", style=disnake.ButtonStyle.secondary)
    async def change_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        self.stop()
        for child in self.children:
            child.disabled = True
        await inter.response.edit_message(
            content=(
                "Укажи свой правильный Riot ID — напиши его здесь в формате `Ник#TAG`\n"
                "Например: `ProPlayer#EUW`\n\n"
                "У тебя есть **5 минут**."
            ),
            embed=None,
            view=self,
        )
        # Ждём текстового ответа в DM
        try:
            msg = await inter.bot.wait_for(
                "message",
                check=lambda m: m.author.id == self.discord_id and isinstance(m.channel, disnake.DMChannel),
                timeout=300,
            )
            riot_id = msg.content.strip()
            if "#" not in riot_id:
                await msg.reply("❌ Неверный формат. Нужно `Ник#TAG`. Попробуй `/link` в боте.")
                return

            new_name, new_tag = riot_id.split("#", 1)
            new_name = new_name.strip()
            new_tag  = new_tag.strip()

            status = await msg.reply(f"🔍 Проверяю `{new_name}#{new_tag}`...")

            rank_data = await riot_api.get_player_rank(new_name, new_tag)
            if rank_data is None:
                await status.edit(content=(
                    f"❌ Аккаунт `{new_name}#{new_tag}` не найден.\n"
                    f"Проверь правильность и попробуй `/link` в Discord-боте."
                ))
                return

            db_manager.link_player(
                discord_id=self.discord_id,
                riot_name=new_name,
                riot_tag=new_tag,
                region="eu",
                rank=rank_data["rank"],
                rank_weight=rank_data["weight"],
                elo=rank_data["elo"],
            )

            emoji = riot_api.rank_emoji(rank_data["rank"])
            await status.edit(content=(
                f"✅ Аккаунт обновлён!\n"
                f"**{new_name}#{new_tag}** {emoji} {rank_data['rank']} ({rank_data['rr']} RR)\n\n"
                f"Теперь ты будешь распознаваться автоматически в следующих матчах."
            ))

        except asyncio.TimeoutError:
            await inter.channel.send("⏰ Время вышло. Используй `/link` в Discord-боте чтобы изменить аккаунт.")

    async def on_timeout(self):
        # Просто тихо истекаем — не спамим в DM
        pass


# ══════════════════════════════════════════════════════════════════════
# UI: один запрос — выбор ника с скрина для Discord-участника
# ══════════════════════════════════════════════════════════════════════

class PickNickView(disnake.ui.View):
    """
    Один Select: ники с скрина (K/D/A в описании) + кнопка «Пропустить».
    Хост выбирает, какой ник на скрине — это данный участник.
    """
    def __init__(self, host, discord_id: int, available_nicks: list,
                 on_pick, on_skip):
        super().__init__(timeout=180)
        self.host = host
        self.discord_id = discord_id
        self.available_nicks = available_nicks  # [{"riot_id", "stats"}, ...]
        self.on_pick = on_pick
        self.on_skip = on_skip
        self._responded = False

        options = []
        for i, n in enumerate(available_nicks[:25]):
            riot_id = (n.get("riot_id") or "").strip() or "?"
            st = n.get("stats") or {}
            desc = f"K/D/A: {st.get('kills',0)}/{st.get('deaths',0)}/{st.get('assists',0)} ACS:{st.get('acs',0)}"[:100]
            options.append(disnake.SelectOption(
                label=riot_id[:100],
                value=str(i),
                description=desc,
            ))

        if options:
            select = disnake.ui.Select(
                placeholder="Выбери ник с скриншота",
                options=options,
                custom_id="pick_nick",
            )
            select.callback = self._select_callback
            self.add_item(select)

    async def _select_callback(self, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост может сопоставлять игроков.", ephemeral=True)
        if self._responded:
            return
        self._responded = True
        self.stop()

        idx = int(inter.values[0])
        item = self.available_nicks[idx]
        riot_id = item.get("riot_id") or ""
        stats = item.get("stats") or {}
        member = inter.guild.get_member(self.discord_id)

        await inter.response.edit_message(
            content=f"✅ {member.mention if member else self.discord_id} → `{riot_id}`",
            embed=None,
            view=None,
        )
        await self.on_pick(riot_id, stats)

    @disnake.ui.button(label="⏭ Пропустить", style=disnake.ButtonStyle.secondary, row=1)
    async def skip_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.host.id:
            return await inter.response.send_message("Только хост может управлять этим.", ephemeral=True)
        if self._responded:
            return
        self._responded = True
        self.stop()
        await inter.response.edit_message(
            content="⏭ Игрок пропущен, ELO не обновится.",
            embed=None,
            view=None,
        )
        await self.on_skip()

    async def on_timeout(self):
        if not self._responded:
            self._responded = True
            await self.on_skip()


# ══════════════════════════════════════════════════════════════════════
# Финализация: подсчёт ELO и публикация итогового embed
# ══════════════════════════════════════════════════════════════════════

async def _finalize_match(channel, parsed: dict, match_data: dict,
                          matched_stats: dict, linked: dict):
    """
    Считает ELO для всех сопоставленных игроков и публикует итог.
    matched_stats: {discord_id: {team, kills, deaths, assists, acs, hs_percent}}
    """
    winner_side = parsed.get("winner", "?")
    score_atk   = parsed.get("score_attack", "?")
    score_def   = parsed.get("score_defense", "?")
    players_raw = parsed.get("players", [])

    team1_ids  = match_data.get("team1_ids", [])
    team2_ids  = match_data.get("team2_ids", [])
    team1_side = match_data.get("team1_side", "attack")
    team2_side = "defense" if team1_side == "attack" else "attack"

    if winner_side == team1_side:
        winner_ids   = [uid for uid in team1_ids if uid in matched_stats]
        loser_ids    = [uid for uid in team2_ids if uid in matched_stats]
        winner_label = "🔵 Команда 1 (Атака)"
    elif winner_side == team2_side:
        winner_ids   = [uid for uid in team2_ids if uid in matched_stats]
        loser_ids    = [uid for uid in team1_ids if uid in matched_stats]
        winner_label = "🔴 Команда 2 (Защита)"
    else:
        winner_ids   = []
        loser_ids    = list(matched_stats.keys())
        winner_label = f"Сторона: {winner_side}"

    # Обновляем ELO
    elo_changes = {}
    if winner_ids or loser_ids:
        elo_changes = elo_engine.update_elos_after_match(
            winner_ids=winner_ids,
            loser_ids=loser_ids,
            stats_by_id=matched_stats,
        )

    # Обновляем linked из БД (там могли появиться новые авто-привязки)
    all_ids = team1_ids + team2_ids
    linked_fresh = db_manager.get_players_bulk(all_ids)

    # ── Embed результатов ──────────────────────────────────────────────
    embed = disnake.Embed(title="🏆 Матч завершён!", color=disnake.Color.gold())
    embed.add_field(name="🥇 Победитель", value=winner_label, inline=True)
    embed.add_field(name="📊 Счёт",       value=f"**{score_atk} : {score_def}**", inline=True)
    embed.add_field(name="\u200b",         value="\u200b", inline=True)

    # Таблица по игрокам со скриншота
    perf_lines = []
    for p in players_raw:
        riot_id = p.get("riot_id", "?")
        k  = p.get("kills",   0)
        d  = p.get("deaths",  0)
        a  = p.get("assists", 0)
        acs = p.get("acs",   0)
        hs  = p.get("hs_percent")
        hs_str = f" HS:{hs}%" if hs is not None else ""
        team_icon = "🔵" if p.get("team") == "attack" else "🔴"
        perf_lines.append(f"{team_icon} `{riot_id}` {k}/{d}/{a} ACS:{acs}{hs_str}")

    if perf_lines:
        embed.add_field(
            name="📋 Статистика",
            value="\n".join(perf_lines),
            inline=False,
        )

    # ELO изменения
    elo_lines = []
    for uid, ch in elo_changes.items():
        entry = linked_fresh.get(uid) or linked.get(uid) or {}
        name  = entry.get("riot_name") or f"<@{uid}>"
        delta = ch["delta"]
        sign  = "+" if delta >= 0 else ""
        label = elo_engine.custom_elo_to_rank_label(ch["new"])
        won   = uid in winner_ids
        result_icon = "✅" if won else "❌"
        elo_lines.append(
            f"{result_icon} `{name}`: **{ch['old']}** → **{ch['new']}** ({sign}{delta}) {label}"
        )

    if elo_lines:
        embed.add_field(
            name="📈 Custom ELO",
            value="\n".join(elo_lines),
            inline=False,
        )

    unmatched_count = len(players_raw) - len(matched_stats)
    if unmatched_count > 0:
        embed.set_footer(
            text=f"⚠️ {unmatched_count} игроков пропущено — их ELO не обновилось. "
                 "Следующий раз попроси привязать /link заранее."
        )

    # Записываем историю в БД
    map_name = None  # TODO: пробросить из match_data если будет храниться
    db_manager.record_match_result(
        winner_ids=winner_ids,
        loser_ids=loser_ids,
        stats_by_id=matched_stats,
        elo_changes=elo_changes,
        map_name=map_name,
    )

    await channel.send(embed=embed)


def setup(bot):
    bot.add_cog(MatchCog(bot))
    bot.add_cog(ScreenshotListener(bot))

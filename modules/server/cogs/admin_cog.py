import asyncio
import datetime

import disnake
from disnake.ext import commands


async def _bulk_delete_messages(channel: disnake.TextChannel, limit: int) -> int:
    """
    Удаляет последние limit сообщений.
    Свежие (<14 дней) — bulk API (до 100 за запрос), старые — по одному.
    """
    cutoff = disnake.utils.utcnow() - datetime.timedelta(days=14)
    bulk: list[disnake.Message] = []
    singles: list[disnake.Message] = []

    async for msg in channel.history(limit=limit):
        if msg.pinned:
            continue
        if msg.created_at >= cutoff:
            bulk.append(msg)
        else:
            singles.append(msg)

    deleted = 0

    for i in range(0, len(bulk), 100):
        chunk = bulk[i : i + 100]
        if len(chunk) == 1:
            try:
                await chunk[0].delete()
                deleted += 1
            except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
                pass
        else:
            try:
                await channel.delete_messages(chunk)
                deleted += len(chunk)
            except disnake.HTTPException:
                for msg in chunk:
                    try:
                        await msg.delete()
                        deleted += 1
                    except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
                        pass

    if singles:
        async def _delete_one(msg: disnake.Message) -> bool:
            try:
                await msg.delete()
                return True
            except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
                return False

        results = await asyncio.gather(*(_delete_one(m) for m in singles))
        deleted += sum(1 for ok in results if ok)

    return deleted


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name="move", description="Переместить всех участников из одного голосового канала в другой")
    async def move(
        self,
        inter: disnake.ApplicationCommandInteraction,
        source: disnake.VoiceChannel = commands.Param(
            description="Откуда забрать участников",
        ),
        target: disnake.VoiceChannel = commands.Param(
            description="Куда переместить участников",
        ),
    ):
        if not inter.guild:
            return await inter.response.send_message(
                "Эта команда работает только на сервере.",
                ephemeral=True,
            )

        if source.id == target.id:
            return await inter.response.send_message(
                "Нужно выбрать два разных голосовых канала.",
                ephemeral=True,
            )

        members = list(source.members)
        if not members:
            return await inter.response.send_message(
                f"В {source.mention} сейчас никого нет.",
                ephemeral=True,
            )

        bot_member = inter.guild.me
        bot_permissions = target.permissions_for(bot_member) if bot_member else None
        if not bot_permissions or not bot_permissions.move_members:
            return await inter.response.send_message(
                "У меня нет права `Перемещать участников` для этого канала.",
                ephemeral=True,
            )

        if target.user_limit and len(target.members) + len(members) > target.user_limit:
            return await inter.response.send_message(
                f"В {target.mention} не хватит мест для всех участников.",
                ephemeral=True,
            )

        await inter.response.defer(ephemeral=True)

        moved = []
        failed = []
        for member in members:
            try:
                if member.voice and member.voice.channel and member.voice.channel.id == source.id:
                    await member.move_to(target)
                    moved.append(member)
            except disnake.Forbidden:
                failed.append(member)
            except disnake.HTTPException:
                failed.append(member)

        if failed:
            failed_names = ", ".join(member.display_name for member in failed[:5])
            if len(failed) > 5:
                failed_names += f" и ещё {len(failed) - 5}"
            content = (
                f"Перемещено: **{len(moved)}** из **{len(members)}** в {target.mention}.\n"
                f"Не получилось перенести: {failed_names}."
            )
        else:
            content = f"Перемещено участников: **{len(moved)}** из {source.mention} в {target.mention}."

        await inter.edit_original_response(content=content)

    @commands.slash_command(name="clean", description="Удалить последние сообщения в этом чате")
    async def clean(
        self,
        inter: disnake.ApplicationCommandInteraction,
        amount: int = commands.Param(
            ge=1,
            le=100,
            description="Сколько последних сообщений удалить (1-100)",
        ),
    ):
        if not isinstance(inter.channel, disnake.TextChannel):
            return await inter.response.send_message(
                "Эта команда работает только в текстовом канале.",
                ephemeral=True,
            )

        permissions = inter.channel.permissions_for(inter.author)
        if not permissions.manage_messages:
            return await inter.response.send_message(
                "Нужны права `Управлять сообщениями`.",
                ephemeral=True,
            )

        bot_member = inter.guild.me if inter.guild else None
        bot_permissions = inter.channel.permissions_for(bot_member) if bot_member else None
        if not bot_permissions or not bot_permissions.manage_messages:
            return await inter.response.send_message(
                "У меня нет права `Управлять сообщениями` в этом канале.",
                ephemeral=True,
            )

        await inter.response.defer(ephemeral=True)
        deleted = await _bulk_delete_messages(inter.channel, amount)
        await inter.edit_original_response(
            content=f"Удалено сообщений: **{deleted}**."
        )


def setup(bot):
    bot.add_cog(AdminCog(bot))

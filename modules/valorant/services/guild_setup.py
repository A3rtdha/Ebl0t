import disnake

CATEGORY_NAME = "🤖 VALORANT HUB"
INVITE_CHANNEL_NAME = "📢-сбор-на-кастомки"
CUSTOMS_CHANNEL_NAME = "📋-создание-кастомок"
VALORANT_ROLE_NAME = "Valorant"
VALORANT_ROLE_ID = 1474962323021234308  # legacy: если роль переименовали, но ID тот же
VALORANT_ROLE_COLOR = disnake.Color.from_rgb(255, 70, 85)


def get_valorant_role(guild: disnake.Guild) -> disnake.Role | None:
    """Синхронный поиск роли (без создания)."""
    return disnake.utils.get(guild.roles, name=VALORANT_ROLE_NAME) or guild.get_role(VALORANT_ROLE_ID)


async def get_or_create_valorant_role(guild: disnake.Guild) -> disnake.Role | None:
    """Роль Valorant для пинга и прав; создаёт, если на сервере нет."""
    role = get_valorant_role(guild)
    if role:
        return role
    try:
        return await guild.create_role(
            name=VALORANT_ROLE_NAME,
            color=VALORANT_ROLE_COLOR,
            mentionable=True,
            reason="Eblot: роль для hub кастомок",
        )
    except disnake.Forbidden:
        return None


async def get_or_create_hub(guild: disnake.Guild):
    """Находит или создает категорию и текстовые каналы для бота"""
    
    category = disnake.utils.get(guild.categories, name=CATEGORY_NAME)
    if not category:
        category = await guild.create_category(name=CATEGORY_NAME)
    
    # Канал для анонсов (пинг, сбор)
    invite_channel = next(
        (c for c in category.channels if isinstance(c, disnake.TextChannel) and c.name == INVITE_CHANNEL_NAME),
        None
    )
    if not invite_channel:
        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(send_messages=False),
            guild.me: disnake.PermissionOverwrite(send_messages=True)
        }
        invite_channel = await guild.create_text_channel(
            name=INVITE_CHANNEL_NAME, 
            category=category,
            overwrites=overwrites,
            topic="Здесь бот тегает всех и собирает кастомки"
        )
    
    # Канал для создания кастомок — писать могут только с ролью Valorant
    customs_channel = next(
        (c for c in category.channels if isinstance(c, disnake.TextChannel) and c.name == CUSTOMS_CHANNEL_NAME),
        None
    )
    if not customs_channel:
        role = await get_or_create_valorant_role(guild)
        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=True, send_messages=False),
            guild.me: disnake.PermissionOverwrite(send_messages=True),
        }
        if role:
            overwrites[role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True)
        customs_channel = await guild.create_text_channel(
            name=CUSTOMS_CHANNEL_NAME,
            category=category,
            overwrites=overwrites,
            topic="Создание кастомок. Писать могут только участники с ролью Valorant."
        )
    
    return category, invite_channel, customs_channel

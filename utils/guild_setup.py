import disnake

CATEGORY_NAME = "🤖 VALORANT HUB"
INVITE_CHANNEL_NAME = "📢-сбор-на-кастомки"
CUSTOMS_CHANNEL_NAME = "📋-создание-кастомок"
VALORANT_ROLE_ID = 1474962323021234308  # запасной поиск роли по ID (если имя другое)

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
        role = disnake.utils.get(guild.roles, name="Valorant") or guild.get_role(VALORANT_ROLE_ID)
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

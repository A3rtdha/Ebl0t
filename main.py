import os
import disnake
import logging
import traceback
from disnake.ext import commands
from dotenv import load_dotenv

# 1. Настраиваем логирование (Чтобы видеть ВСЁ, что происходит)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("Bot")

# Загружаем переменные окружения
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Настраиваем Intents
intents = disnake.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True

# Инициализируем бота
# ВАЖНО: Убедись, что прокси указан верно (или убери аргумент proxy, если используешь TUN-режим)
bot = commands.InteractionBot(
    intents=intents,
    proxy="http://127.0.0.1:7897" 
)

@bot.event
async def on_ready():
    logger.info(f'✅ Бот {bot.user} успешно запущен!')
    logger.info('--- Слэш-команды синхронизированы ---')

@bot.event
async def on_slash_command_error(inter, error):
    """Глобальный отлов ошибок в командах"""
    logger.error(f"Ошибка в команде {inter.application_command.name}: {error}")
    # Пишем полный трейсбэк в консоль
    traceback.print_exc()
    
    # Пытаемся ответить пользователю, если это возможно
    try:
        if not inter.response.is_done():
            await inter.response.send_message(f"❌ Произошла ошибка: {error}", ephemeral=True)
        else:
            await inter.followup.send(f"❌ Произошла ошибка: {error}", ephemeral=True)
    except:
        pass

def load_cogs():
    """Загрузка модулей с подробным отчетом об ошибках"""
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py') and filename != '__init__.py':
            try:
                bot.load_extension(f'cogs.{filename[:-3]}')
                logger.info(f'📦 Модуль {filename} загружен успешно.')
            except Exception as e:
                logger.error(f'❌ Ошибка при загрузке модуля {filename}:')
                logger.error(e)
                traceback.print_exc() # Покажет конкретную строку с ошибкой

if __name__ == '__main__':
    load_cogs()
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.critical(f"Не удалось запустить бота: {e}")

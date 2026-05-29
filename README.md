# Valorant Custom Bot (Eblot)

Discord-бот для автоматизации кастомных матчей в Valorant: лобби, голосовые каналы, дашборд, распознавание скриншотов и Custom ELO.

## Возможности

### Лобби и матч
- `/custom` — создание кастомки (режим **RANDOM**; **VOTED** в планах)
- Голосовой канал ожидания, кнопка «ВСЕ ГОТОВЫ» (только хост)
- Dashboard: **TEAM**, **MAP**, **AGENTS**, персональный **REROLL**
- Авто-создание каналов Attack / Defense и перемещение игроков
- `/finish` — завершение матча, OCR scoreboard (Gemini Vision + Tesseract fallback), wizard исхода
- Aftermatch: сбор игроков в общий голосовой канал после `/finish`

### Профиль и статистика
- `/link` — привязка Riot ID
- `/profile`, `/stats`, `/history` — карточка и статистика по кастомкам
- `/leaderboard` — топ по Custom ELO
- `/rank_refresh` — обновление ranked-ранга из Riot API
- `/unlink` — отвязка аккаунта

### Утилиты
- `/move` — перенос всех участников из одного голосового канала в другой
- `/clean` — удаление последних сообщений в чате (нужны права модератора)
- `/ping` — проверка связи и зависимостей

## Технологии

- Python 3.10+
- [disnake](https://github.com/DisnakeDev/disnake) (форк discord.py)
- JSON-хранилище (`data/data.json`), Henrik Dev API, Gemini Vision / Tesseract OCR
- HTTP-прокси через `.env` (Discord и Gemini)

## Установка и запуск

1. **Зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Окружение:** скопируй [`.env.example`](.env.example) → `.env` и заполни:
   | Переменная | Назначение |
   |------------|------------|
   | `DISCORD_TOKEN` | Токен бота (обязательно) |
   | `HENRIK_API_KEY` | Riot ranked через Henrik Dev API |
   | `GEMINI_API_KEY` | OCR scoreboard через Gemini Vision |
   | `GEMINI_MODEL` | Модель Gemini (по умолчанию `gemini-2.5-flash`) |
   | `PROXY` | Прокси для Discord (http/https/socks5) |
   | `GEMINI_PROXY` | Отдельный прокси для Gemini (если не задан — берётся `PROXY`) |
   | `TESSERACT_CMD` | Путь к `tesseract.exe` на Windows |

3. **Запуск:**
   ```bash
   python main.py
   ```
   На Windows можно использовать [`start.ps1`](start.ps1) — проверка прокси и защита от двойного запуска.

4. **Docker (опционально):**
   ```bash
   docker build -t eblot .
   docker run --env-file .env eblot
   ```

## Структура проекта

```
cogs/     — slash-команды (custom, match, profile, admin, debug)
ui/       — views, modals, dashboard
utils/    — OCR, ELO, БД, Riot API, aftermatch voices
data/     — game_data.json (статика); runtime JSON — в .gitignore
scripts/  — локальные тесты OCR и ручной apply матча
proxy/    — локальные sing-box конфиги (в .gitignore)
```

Runtime-данные (`data/data.json`, `data/active_matches.json`) создаются ботом автоматически и не коммитятся.

## Dev-утилиты

```bash
# Тест парсера скриншота (нужен локальный PNG)
python scripts/test_screenshot_parse.py path/to/scoreboard.png

# Ручной apply матча из распознанного scoreboard
python scripts/apply_match_from_screen.py
```

## Документация

- [ROADMAP.md](ROADMAP.md) — план разработки
- [VALORANT_CUSTOMS_LOGIC.md](VALORANT_CUSTOMS_LOGIC.md) — логика лобби и матча

---
*Developed by [Aertdha]*

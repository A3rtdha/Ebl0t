# Eblot

Discord-бот для игрового сообщества: кастомки, рейтинг, голосовая активность и серверные утилиты. Сейчас основной модуль — **Valorant customs**; архитектура рассчитана на добавление других режимов и фич.

## Модули

### Valorant — кастомки
- `/custom` — лобби только в **📋-создание-кастомок** (режим **RANDOM**; **VOTED** в планах)
- `/dev` — тот же флоу без пинга и анонса (только владелец, ID в `customs_cog.py`)
- Голос «Ожидание», кнопка «ВСЕ ГОТОВЫ», дашборд **TEAM / MAP / AGENTS / REROLL**
- `/finish` — OCR scoreboard (Gemini + Tesseract), wizard, Custom ELO
- Aftermatch-голос после матча

### Профиль и рейтинг (Valorant)
- `/link`, `/profile`, `/stats`, `/history`, `/leaderboard`, `/rank_refresh`, `/unlink`
- Custom ELO и звания Eblot (отдельно от ranked Valorant)

### Сервер
- `/move`, `/clean`, `/ping`
- `/voice_stats`, `/voice_top` — время в голосовых на сервере

## Технологии

- Python 3.10+
- [disnake](https://github.com/DisnakeDev/disnake)
- JSON (`data/`), Henrik Dev API, Gemini Vision / Tesseract OCR
- Прокси через `.env` (Discord и Gemini)

## Установка

1. `pip install -r requirements.txt`
2. Скопируй [`.env.example`](.env.example) → `.env` (минимум `DISCORD_TOKEN`)
3. `python main.py` или [`start.ps1`](start.ps1) (Windows)
4. Docker: `docker build -t eblot .` → `docker run --env-file .env eblot`

| Переменная | Назначение |
|------------|------------|
| `DISCORD_TOKEN` | Токен бота |
| `PROXY` / `GEMINI_PROXY` | Прокси |
| `HENRIK_API_KEY` | Riot ranked |
| `GEMINI_API_KEY` | OCR scoreboard |
| `TESSERACT_CMD` | Tesseract на Windows |
| `LOG_LEVEL` | Логи (по умолчанию `INFO`) |

Роль **Valorant** для hub кастомок: бот создаёт при первом `/custom`, если её ещё нет (`Manage Roles`).

## Структура

Код живёт в `modules/` (`valorant`, `voice`, `server`), `core/` и `shared/`. Подробнее: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```
core/           — загрузка расширений
modules/        — реализация по доменам
shared/         — общий UI-теминг
data/           — game_data.json; runtime JSON в .gitignore
scripts/        — локальные тесты OCR
```

## Документация

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — папки и флоу матча
- [ROADMAP.md](ROADMAP.md) — план по модулям
- [VALORANT_CUSTOMS_LOGIC.md](VALORANT_CUSTOMS_LOGIC.md) — флоу кастомок Valorant

---
*Developed by [Aertdha]*

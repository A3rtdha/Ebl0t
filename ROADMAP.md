# Roadmap Eblot

Eblot — мультимодульный бот для Discord-сообщества. Ниже — план по **модулю Valorant** и общей инфраструктуре.

## Фундамент
- [x] disnake, логи, proxy, JSON-БД
- [x] Обработка ошибок slash-команд
- [x] Модульная структура (`core/`, `modules/`, `shared/`, shims) — см. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Valorant — лобби
- [x] Hub: категория, 📢-сбор, 📋-создание-кастомок, роль Valorant
- [x] `/custom` только в канале кастомок; `/dev` для тихих тестов
- [x] ГК «Ожидание», «ВСЕ ГОТОВЫ» (host-only)
- [x] Валидация чётности (в коде есть, для тестов отключена)

## Valorant — RANDOM
- [x] Dashboard (embed + кнопки): TEAM, MAP, AGENTS, REROLL (лимит 3)
- [x] Баланс команд по skill/ELO
- [x] Реролл составов после TEAM, оценка качества split
- [x] `map_name` в history матча
- [x] Нечётный состав (5v4): лишний игрок на сторону с лучшим ELO-балансом

## Valorant — VOTED (драфт)
- [ ] Капитаны, баны карт, выбор стороны

## Valorant — матч и ELO
- [x] Attack/Defense ГК, move, `/finish`, OCR, wizard
- [x] Custom ELO, aftermatch voice
- [ ] Таймер перед стартом

## Профиль (Valorant)
- [x] `/link`, `/profile`, `/stats`, `/history`, `/leaderboard`, `/rank_refresh`, `/unlink`

## Сервер и инфра
- [x] `/move`, `/clean`, `/ping`
- [x] `/voice_stats`, `/voice_top` (чекпоинты, восстановление после рестарта)
- [ ] PostgreSQL вместо JSON

## Защита рейтинга и OCR (TODO)
- [ ] Анти-абьюз: одинаковые счёта, слишком быстрый матч, минимальный diff ELO
- [ ] OCR: ник+тег, ручное сопоставление на скрине, re-link
- [ ] LFP/LFT (низкий приоритет)

## Не планируется
- Планировщик scrim, лента результатов, amend ELO, persistent lobby, авто-роли по рангу Riot, spectators, rosters

## Идеи (вне Valorant)
- [ ] Другие игры / режимы как отдельные модули
- [ ] Таблица voice-time в закреплённом канале
- [ ] Components V2 для дашборда (когда стабильно с кнопками в disnake)

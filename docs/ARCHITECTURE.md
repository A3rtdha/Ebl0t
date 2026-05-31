# Eblot architecture

Eblot is organized as a small **core** plus **feature modules**.

## Layout

```
core/                          # Bot bootstrap helpers
  extension_loader.py          # EXTENSIONS list + load_extensions()
  config.py, paths.py, network_retry.py

shared/
  ui_theme.py                  # Brand colors, embed helpers

modules/
  server/cogs/                 # /move, /clean, /ping
  voice/
    cog/                       # /voice_stats, /voice_top
    storage/                   # voice_time persistence
  valorant/
    cogs/                      # customs, match, profile
    ui/                        # lobby, dashboard, modals, outcome, finish views
    services/                  # ELO, OCR, match state, Riot API, guild setup, …

data/                          # Runtime JSON + game_data.json
main.py                        # Entry point
```

## Valorant match result flow

1. `/finish` → `match_cog` → screenshot listener or manual modal
2. `match_outcome` — host picks winner + score
3. `result_flow` + `result_flow_state` — nick wizard, auto-link, ELO finalize
4. `finish_views` — OCR review, parse fail, pick-nick, link confirm UI

## Import rules

| Layer | May import |
|--------|------------|
| `modules/*/cogs` | `services`, `ui`, `shared`, `core` |
| `modules/*/ui` | `services`, `shared` — **not** `cogs` |
| `modules/*/services` | `core`, other services — **not** `disnake` UI |
| `main.py` | `core`, `modules.*.setup` hooks only |

Use `from modules.<feature>.services import …` (or `shared`, `core`) — no root-level `utils/` package.

## Adding a feature module

1. Create `modules/<name>/` with `cogs/`, optional `ui/` and `services/`
2. Implement `def setup(bot):` in each cog file
3. Add paths to `core/extension_loader.EXTENSIONS`

# Agent onboarding — Eblot

Discord bot for a gaming community (Valorant customs, profiles, voice stats, server tools).

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env   # set DISCORD_TOKEN at minimum
python main.py
```

Windows: [`start.ps1`](start.ps1) checks for `.env` then runs `main.py`.

`main.py` imports `core.config` first so `.env` is loaded once via `load_dotenv`.

## Environment (`.env`)

| Variable | Required | Notes |
|----------|----------|--------|
| `DISCORD_TOKEN` | yes | Bot token |
| `PROXY` | no | Discord API proxy |
| `LOG_LEVEL` | no | Default `INFO` |
| `HENRIK_API_KEY` | no | Valorant ranked lookup |
| `GEMINI_API_KEY` | no | Scoreboard OCR (primary) |
| `GEMINI_MODEL` | no | Default `gemini-2.5-flash` |
| `GEMINI_PROXY` | no | Falls back to `PROXY` |

See [`.env.example`](.env.example) for comments.

## Extensions (loaded in `core/extension_loader.py`)

- `modules.server.cogs.admin_cog`
- `modules.server.cogs.debug_cog`
- `modules.voice.cog.voice_stats_cog`
- `modules.valorant.cogs.customs_cog`
- `modules.valorant.cogs.match_cog`
- `modules.valorant.cogs.profile_cog`

Implementation lives under `modules/`, `core/`, and `shared/` only.

Valorant `on_ready` / guild join: `modules.valorant.setup.register` and `on_guild_join` (SetupModeView, aftermatch channels).

## Architecture & product docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — domains, import rules, file layout
- [VALORANT_CUSTOMS_LOGIC.md](VALORANT_CUSTOMS_LOGIC.md) — customs lobby and match flow
- [ROADMAP.md](ROADMAP.md) — roadmap

## Coding conventions

- **Python 3.10+**, [disnake](https://github.com/DisnakeDev/disnake)
- Match existing style: Russian user-facing strings, English identifiers and logs where already used
- **Minimal diffs** — do not refactor unrelated code in the same change
- **UI** in `modules/valorant/ui/` (or `modules/<feature>/ui/`) — no imports from `cogs/`
- **Services** in `modules/<feature>/services/` — no Discord UI here
- **State** — JSON under `data/`; use `core/paths.py` for path constants
- **Secrets** — never commit `.env`; do not log tokens
- **Cogs** — one `setup(bot)` per extension; register only in `core/extension_loader.py`
- New features: add `modules/<name>/` with `cogs/`, optional `ui/`, `services/`; wire in `EXTENSIONS`

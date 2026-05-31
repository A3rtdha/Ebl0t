"""Canonical filesystem paths for runtime JSON and static game data."""

from __future__ import annotations

from pathlib import Path

from core.config import ROOT

DATA_DIR = ROOT / "data"

# Valorant player profiles / Custom ELO (db_manager)
VALORANT_PROFILE_JSON = DATA_DIR / "data.json"
ACTIVE_MATCHES_JSON = DATA_DIR / "active_matches.json"
GAME_DATA_JSON = DATA_DIR / "game_data.json"

# Voice activity
VOICE_STATS_JSON = DATA_DIR / "voice_stats.json"
VOICE_ACTIVE_JSON = DATA_DIR / "voice_active.json"

"""Central env and paths for Eblot. Import this module before reading os.getenv elsewhere."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
PROXY = os.getenv("PROXY", "").strip() or None
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
HENRIK_API_KEY = os.getenv("HENRIK_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
GEMINI_PROXY = (os.getenv("GEMINI_PROXY", "") or os.getenv("PROXY", "")).strip() or None

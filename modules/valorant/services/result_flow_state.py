"""Shared state for post-match result flow (locks, active channels, wizard sessions)."""

from __future__ import annotations

import asyncio
from collections import defaultdict

result_flow_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
active_result_channels: set[int] = set()
wizard_sessions: dict[int, str] = {}


def is_channel_busy(channel_id: int) -> bool:
    return channel_id in active_result_channels

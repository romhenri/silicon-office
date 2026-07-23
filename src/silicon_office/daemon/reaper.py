"""Background sweeps: crash detection and pending pid/name resolution.

Runs on a plain timer rather than reacting to hook events, because a crashed
process (kill -9, lid close) never fires SessionEnd -- this is the only thing
that can notice such a process is gone (RNF-04).
"""

from __future__ import annotations

import asyncio

from silicon_office.daemon.broadcaster import Broadcaster
from silicon_office.daemon.registry import SessionRegistry


async def reaper_loop(
    registry: SessionRegistry, broadcaster: Broadcaster, interval: float
) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            registry.resolve_pending_identities()
            for session_id in registry.reap_dead():
                await broadcaster.broadcast_diff(session_id, "remove", None)
        except Exception:
            # A sweep must never take the daemon down.
            pass


async def periodic_snapshot_loop(broadcaster: Broadcaster, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await broadcaster.broadcast_snapshot()
        except Exception:
            pass

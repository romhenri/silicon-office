"""Daemon entrypoint: wires the UDP listener, registry, broadcaster, and
reaper together. Pure stdlib -- no pygame import anywhere on this path, per
RNF-01's low-overhead-collector requirement.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any

from silicon_office.common.constants import (
    REAPER_INTERVAL_SECONDS,
    SNAPSHOT_INTERVAL_SECONDS,
    STATE_IDLE,
    TCP_HOST,
    TCP_PORT,
    UDP_HOST,
    UDP_PORT,
)
from silicon_office.common.schema import AgentRecord, HookEvent
from silicon_office.daemon.broadcaster import Broadcaster
from silicon_office.daemon.reaper import periodic_snapshot_loop, reaper_loop
from silicon_office.daemon.registry import SessionRegistry, list_live_sessions
from silicon_office.daemon.state_machine import project_name_from_cwd
from silicon_office.daemon.udp_listener import start_udp_listener


def _cold_start(registry: SessionRegistry) -> None:
    now = time.time()
    for info in list_live_sessions():
        session_id = info.get("sessionId")
        if not session_id:
            continue
        cwd = info.get("cwd", "")
        registry.seed(
            AgentRecord(
                session_id=session_id,
                project_name=info.get("name") or project_name_from_cwd(cwd),
                cwd=cwd,
                pid=info.get("pid"),
                entrypoint=info.get("entrypoint", "unknown"),
                state=STATE_IDLE,
                action_label="Idle",
                state_since=now,
            )
        )


async def run() -> None:
    registry = SessionRegistry()
    _cold_start(registry)
    broadcaster = Broadcaster(registry)

    def on_event(payload: dict[str, Any]) -> None:
        try:
            event = HookEvent.from_dict(payload)
        except Exception:
            return
        record, op = registry.apply_event(event, time.time())
        if op in ("upsert", "remove"):
            asyncio.ensure_future(broadcaster.broadcast_diff(event.session_id, op, record))

    udp_transport = await start_udp_listener(UDP_HOST, UDP_PORT, on_event)
    tcp_server = await broadcaster.start_server(TCP_HOST, TCP_PORT)

    print(
        f"claude-vo-daemon listening: UDP {UDP_HOST}:{UDP_PORT}, TCP {TCP_HOST}:{TCP_PORT} "
        f"({len(registry.all())} agent(s) found at cold start)",
        file=sys.stderr,
        flush=True,
    )

    asyncio.ensure_future(reaper_loop(registry, broadcaster, REAPER_INTERVAL_SECONDS))
    asyncio.ensure_future(periodic_snapshot_loop(broadcaster, SNAPSHOT_INTERVAL_SECONDS))

    try:
        async with tcp_server:
            await tcp_server.serve_forever()
    finally:
        udp_transport.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

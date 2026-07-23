"""TCP broadcaster: pushes state snapshots/diffs to whatever frontends connect.

Fault tolerance is the point of this module: sending is a no-op with zero
connected clients (diffs are never queued -- unbounded growth if a frontend
never shows up would be worse than losing intermediate history, since a fresh
snapshot is always sent on connect), and a write to a dead socket just drops
that one client rather than raising.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from silicon_office.common.ipc import encode_message
from silicon_office.common.schema import AgentRecord, make_diff_message, make_snapshot_message
from silicon_office.daemon.registry import SessionRegistry

_DEAD_SOCKET_ERRORS = (ConnectionResetError, BrokenPipeError, OSError)


class Broadcaster:
    def __init__(self, registry: SessionRegistry) -> None:
        self._registry = registry
        self._clients: set[asyncio.StreamWriter] = set()

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._clients.add(writer)
        try:
            await self._write(writer, make_snapshot_message(self._registry.all(), time.time()))
            # We don't expect the frontend to send anything, but we must keep
            # reading so a closed connection is detected (read() returns b"").
            while True:
                chunk = await reader.read(1024)
                if not chunk:
                    break
        except _DEAD_SOCKET_ERRORS:
            pass
        finally:
            self._clients.discard(writer)
            writer.close()

    async def _write(self, writer: asyncio.StreamWriter, message: dict) -> bool:
        try:
            writer.write(encode_message(message))
            await writer.drain()
            return True
        except _DEAD_SOCKET_ERRORS:
            return False

    async def broadcast_diff(
        self, session_id: str, op: str, agent: Optional[AgentRecord]
    ) -> None:
        if not self._clients:
            return
        message = make_diff_message(session_id, op, agent, time.time())
        await self._broadcast(message)

    async def broadcast_snapshot(self) -> None:
        if not self._clients:
            return
        message = make_snapshot_message(self._registry.all(), time.time())
        await self._broadcast(message)

    async def _broadcast(self, message: dict) -> None:
        dead = []
        for writer in list(self._clients):
            ok = await self._write(writer, message)
            if not ok:
                dead.append(writer)
        for writer in dead:
            self._clients.discard(writer)

    async def start_server(self, host: str, port: int) -> asyncio.AbstractServer:
        return await asyncio.start_server(self.handle_client, host, port)

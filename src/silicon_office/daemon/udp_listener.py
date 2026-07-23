"""Asyncio UDP listener receiving hook events from the emitter."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from silicon_office.common.ipc import decode_message


class HookEventProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_event: Callable[[dict[str, Any]], None]) -> None:
        self._on_event = on_event

    def datagram_received(self, data: bytes, addr: Any) -> None:
        obj = decode_message(data.rstrip(b"\n"))
        if obj is None:
            return
        try:
            self._on_event(obj)
        except Exception:
            # A malformed/unexpected payload must never kill the listener.
            pass

    def error_received(self, exc: Exception) -> None:
        pass


async def start_udp_listener(
    host: str, port: int, on_event: Callable[[dict[str, Any]], None]
) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: HookEventProtocol(on_event), local_addr=(host, port)
    )
    return transport

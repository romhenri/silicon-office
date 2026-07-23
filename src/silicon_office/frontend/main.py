"""Pygame frontend entrypoint.

Main thread owns the render loop and is the only thing that ever mutates
`agents`/`ghosts`/layout state -- NetClient's background thread only ever
pushes parsed messages onto a queue, drained here once per frame. A
top-level try/except around update+draw is the last line of defense so a
single malformed record can't take down the whole process (RNF-04).
"""

from __future__ import annotations

import ctypes
import os
import queue
import time

import pygame


class _SDLRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("w", ctypes.c_int), ("h", ctypes.c_int)]


def _smallest_display_bounds() -> tuple[int, int, int, int]:
    """Pick the connected display with the least screen area (usually the
    laptop panel rather than an external monitor) and return its bounds in
    global desktop coordinates. pygame.display.Info() only ever reports the
    primary display, so multi-monitor placement needs SDL's per-display
    bounds directly -- CDLL(None) reaches the libSDL2 pygame already loaded.
    """
    sdl2 = ctypes.CDLL(None)
    sdl2.SDL_GetDisplayBounds.argtypes = [ctypes.c_int, ctypes.POINTER(_SDLRect)]
    sdl2.SDL_GetDisplayBounds.restype = ctypes.c_int

    smallest: tuple[int, int, int, int] | None = None
    for i in range(pygame.display.get_num_displays()):
        rect = _SDLRect()
        sdl2.SDL_GetDisplayBounds(i, ctypes.byref(rect))
        if smallest is None or rect.w * rect.h < smallest[2] * smallest[3]:
            smallest = (rect.x, rect.y, rect.w, rect.h)
    assert smallest is not None
    return smallest

from silicon_office.common.constants import STATE_ASKING, TCP_HOST, TCP_PORT
from silicon_office.frontend.layout import Layout
from silicon_office.frontend.net_client import NetClient
from silicon_office.frontend.render import (
    TextCache,
    draw_agent,
    draw_background,
    draw_connection_banner,
    draw_usage_bar,
)
from silicon_office.frontend.sprites import get_icon_surface
from silicon_office.frontend.theme import (
    ASKING_FLASH_SECONDS,
    BG_COLOR,
    DESPAWN_ANIM_SECONDS,
    FONT_SIZE_BANNER,
    FONT_SIZE_ID,
    FONT_SIZE_LABEL,
    FONT_SIZE_NAME,
    FONT_SIZE_USAGE,
    FPS,
    SIDEBAR_WIDTH,
    SPAWN_ANIM_SECONDS,
    USAGE_BAR_HEIGHT,
    WINDOW_TITLE,
)
from silicon_office.frontend.usage import UsageTracker


class App:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_icon(get_icon_surface())
        pygame.display.set_caption(WINDOW_TITLE)

        disp_x, disp_y, disp_w, disp_h = _smallest_display_bounds()
        self.window_size = (SIDEBAR_WIDTH, disp_h)
        # SDL only honors window position if set before the window exists.
        os.environ["SDL_VIDEO_WINDOW_POS"] = f"{disp_x + disp_w - SIDEBAR_WIDTH},{disp_y}"
        self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
        self.clock = pygame.time.Clock()

        self.name_cache = TextCache(pygame.font.SysFont(None, FONT_SIZE_NAME))
        self.label_cache = TextCache(pygame.font.SysFont(None, FONT_SIZE_LABEL))
        self.id_cache = TextCache(pygame.font.SysFont(None, FONT_SIZE_ID))
        self.banner_font = pygame.font.SysFont(None, FONT_SIZE_BANNER)
        self.usage_font = pygame.font.SysFont(None, FONT_SIZE_USAGE)

        self.usage_tracker = UsageTracker()
        self.usage_tracker.start()

        self.layout = Layout()
        self.agents: dict[str, dict] = {}
        self.spawn_started: dict[str, float] = {}
        self.asking_since: dict[str, float] = {}
        self.ghosts: dict[str, dict] = {}
        self.connected = False

        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._net = NetClient(TCP_HOST, TCP_PORT, self._queue)
        self._start_time = time.monotonic()

    def _anim_tick(self) -> float:
        return time.monotonic() - self._start_time

    def run(self) -> None:
        self._net.start()
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE:
                    self.window_size = (event.w, event.h)
                    self.screen = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)

            try:
                self._drain_queue()
                self._update_ghosts()
                self._draw()
            except Exception:
                pass

            self.clock.tick(FPS)

        self._net.stop()
        self.usage_tracker.stop()
        pygame.quit()

    def _drain_queue(self) -> None:
        while True:
            try:
                message = self._queue.get_nowait()
            except queue.Empty:
                break
            self._handle_message(message)

    def _handle_message(self, message: dict) -> None:
        mtype = message.get("type")
        now = time.monotonic()
        if mtype == "_conn_status":
            self.connected = bool(message.get("connected"))
        elif mtype == "snapshot":
            agents = message.get("agents", {})
            for sid, agent in agents.items():
                self._upsert_agent(sid, agent, now)
            for sid in list(self.agents):
                if sid not in agents:
                    self._start_despawn(sid)
        elif mtype == "diff":
            sid = message.get("session_id")
            op = message.get("op")
            if op == "upsert" and sid:
                self._upsert_agent(sid, message.get("agent", {}), now)
            elif op == "remove" and sid:
                self._start_despawn(sid)

    def _upsert_agent(self, session_id: str, agent: dict, now: float) -> None:
        is_new = session_id not in self.agents and session_id not in self.ghosts
        self.ghosts.pop(session_id, None)  # a re-spawn cancels any pending fade-out
        was_asking = self.agents.get(session_id, {}).get("state") == STATE_ASKING
        self.agents[session_id] = agent
        if is_new:
            self.spawn_started[session_id] = now
        if agent.get("state") == STATE_ASKING and not was_asking:
            self.asking_since[session_id] = now
        self.layout.sync(set(self.agents) | set(self.ghosts))

    def _start_despawn(self, session_id: str) -> None:
        agent = self.agents.pop(session_id, None)
        if agent is None:
            return
        self.ghosts[session_id] = {"agent": agent, "despawn_started": time.monotonic()}
        self.spawn_started.pop(session_id, None)
        self.asking_since.pop(session_id, None)
        self.layout.sync(set(self.agents) | set(self.ghosts))

    def _update_ghosts(self) -> None:
        now = time.monotonic()
        finished = [
            sid
            for sid, ghost in self.ghosts.items()
            if now - ghost["despawn_started"] >= DESPAWN_ANIM_SECONDS
        ]
        for sid in finished:
            self.ghosts.pop(sid, None)
        if finished:
            self.layout.sync(set(self.agents) | set(self.ghosts))

    def _draw(self) -> None:
        self.screen.fill(BG_COLOR)
        draw_background(self.screen, self.window_size)
        now = time.monotonic()
        anim = self._anim_tick()

        office_size = (self.window_size[0], max(1, self.window_size[1] - USAGE_BAR_HEIGHT))

        for sid, agent in self.agents.items():
            rect = self.layout.desk_rect(sid, office_size)
            if rect is None:
                continue
            rect = rect.move(0, USAGE_BAR_HEIGHT)
            alpha = 1.0
            spawn_started = self.spawn_started.get(sid)
            if spawn_started is not None:
                elapsed = now - spawn_started
                if elapsed < SPAWN_ANIM_SECONDS:
                    alpha = max(0.0, min(1.0, elapsed / SPAWN_ANIM_SECONDS))
                else:
                    self.spawn_started.pop(sid, None)
            boost = 0.0
            asking_since = self.asking_since.get(sid)
            if asking_since is not None and agent.get("state") == STATE_ASKING:
                elapsed = now - asking_since
                if elapsed < ASKING_FLASH_SECONDS:
                    boost = 1.0 - (elapsed / ASKING_FLASH_SECONDS)
                else:
                    self.asking_since.pop(sid, None)
            draw_agent(
                self.screen, rect, agent, anim, alpha, boost,
                self.name_cache, self.label_cache, self.id_cache,
            )

        for sid, ghost in self.ghosts.items():
            rect = self.layout.desk_rect(sid, office_size)
            if rect is None:
                continue
            rect = rect.move(0, USAGE_BAR_HEIGHT)
            elapsed = now - ghost["despawn_started"]
            progress = max(0.0, min(1.0, elapsed / DESPAWN_ANIM_SECONDS))
            draw_agent(
                self.screen, rect, ghost["agent"], anim, 1.0 - progress, 0.0,
                self.name_cache, self.label_cache, self.id_cache,
            )

        if not self.connected:
            draw_connection_banner(self.screen, self.banner_font, self.window_size)

        usage = self.usage_tracker.snapshot()
        draw_usage_bar(self.screen, self.usage_font, self.window_size, usage)

        pygame.display.flip()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()

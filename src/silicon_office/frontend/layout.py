"""Dynamic desk grid with stable slot assignment.

Slot indices are assigned once per session_id and only ever freed (never
reassigned to a different agent's *position* implicitly) -- a new agent
prefers a freed slot over growing the grid, so unrelated avatars never jump
around when some other agent spawns or despawns. The tradeoff: grid capacity
tracks the peak concurrent agent count seen so far and never shrinks, which
can leave a few empty desks after a busy session quiets down. That's judged
better than the alternative of avatars visibly reshuffling.
"""

from __future__ import annotations

import pygame

from silicon_office.frontend.theme import DESK_HEIGHT, DESK_MARGIN, DESK_MAX_WIDTH, DESK_MIN_GAP


class Layout:
    def __init__(self) -> None:
        self._slot_of_session: dict[str, int] = {}
        self._free_slots: list[int] = []
        self._next_slot = 0
        self._rows = 1

    def _assign_slot(self, session_id: str) -> None:
        if session_id in self._slot_of_session:
            return
        if self._free_slots:
            slot = self._free_slots.pop(0)
        else:
            slot = self._next_slot
            self._next_slot += 1
        self._slot_of_session[session_id] = slot

    def _release_slot(self, session_id: str) -> None:
        slot = self._slot_of_session.pop(session_id, None)
        if slot is not None:
            self._free_slots.append(slot)

    def sync(self, session_ids: set[str]) -> None:
        """Reconcile slot assignments with the current set of agent ids."""
        current = set(self._slot_of_session)
        for sid in current - session_ids:
            self._release_slot(sid)
        for sid in session_ids - current:
            self._assign_slot(sid)
        self._recompute_grid()

    def _recompute_grid(self) -> None:
        self._rows = max(1, self._next_slot)

    def desk_rect(self, session_id: str, window_size: tuple[int, int]) -> "pygame.Rect | None":
        """Every agent sits in a single centered column, one row per slot --
        the column width is capped so desks don't stretch absurdly wide on a
        maximized window. Desk height is fixed (DESK_HEIGHT) so desks never
        shrink into each other as more agents join; instead the gap between
        rows shrinks first, from the full DESK_MARGIN down to DESK_MIN_GAP,
        to fit as many rows as possible into the window. If even the minimum
        gap can't make everything fit, the column simply overflows the
        window rather than shrinking desks until they overlap."""
        slot = self._slot_of_session.get(session_id)
        if slot is None:
            return None
        w, h = window_size
        cell_w = min(w, DESK_MAX_WIDTH)
        cell_h = DESK_HEIGHT
        ideal_pitch = cell_h + DESK_MARGIN
        available_pitch = h / self._rows
        pitch = max(cell_h + DESK_MIN_GAP, min(ideal_pitch, available_pitch))
        gap = pitch - cell_h
        total_h = pitch * self._rows
        y_offset = max(0.0, (h - total_h) / 2)
        x = (w - cell_w) / 2 + DESK_MARGIN / 2
        y = y_offset + slot * pitch + gap / 2
        return pygame.Rect(int(x), int(y), int(cell_w - DESK_MARGIN), int(cell_h))

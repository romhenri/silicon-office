"""Procedurally generated pixel-art character sprites.

No external asset files -- each frame is a small grid of single-character
codes, scaled up into a pygame Surface. Clothes ('B') are a fixed Claude
brand orange regardless of state -- state is instead carried by the
corner indicator dot and the Asking pulse ring (both drawn in render.py).
Surfaces are cached per frame name since the grids and palette never
change -- avoids re-rasterizing every frame, which matters for the <3% CPU
budget (RNF-01).
"""

from __future__ import annotations

from functools import lru_cache

import pygame

from silicon_office.common.constants import (
    STATE_ASKING,
    STATE_ERROR,
    STATE_IDLE,
    STATE_WORKING,
)
from silicon_office.frontend.theme import PIXEL_SCALE

WIDTH = 10
HEIGHT = 12

# Row index where hands sit in every frame -- render.py redraws this row on
# top of the desk while Working so hands appear to rest on the tabletop
# instead of being hidden behind it.
HAND_ROW_INDEX = 10

HAIR_COLOR = (140, 100, 65)
SKIN_COLOR = (235, 200, 165)
EYE_COLOR = (35, 35, 40)
ERROR_EYE_COLOR = (210, 60, 60)
MOUTH_COLOR = (150, 90, 80)
CLAUDE_ORANGE = (218, 119, 86)

_BASE_PALETTE = {
    ".": None,
    "H": HAIR_COLOR,
    "S": SKIN_COLOR,
    "E": EYE_COLOR,
    "X": ERROR_EYE_COLOR,
    "M": MOUTH_COLOR,
    "A": SKIN_COLOR,
    "B": CLAUDE_ORANGE,
}

# Eyes open, arms resting at sides -- the idle/default pose.
FRAME_BASE = [
    ".HHHHHH...",
    "HHHHHHHH..",
    "HSSSSSSSH.",
    "HSSESSESH.",
    "HSSSSSSSH.",
    "HSSMMMSSH.",
    ".HSSSSSH..",
    "..BBBBBB..",
    ".BBBBBBBB.",
    ".BBBBBBBB.",
    "AA.BBBB.AA",
    "..BB..BB..",
]

# Eyes shifted to one side -- idle side-eye glance frame.
FRAME_SIDE_EYE = [
    ".HHHHHH...",
    "HHHHHHHH..",
    "HSSSSSSSH.",
    "HSESSESSH.",
    "HSSSSSSSH.",
    "HSSMMMSSH.",
    ".HSSSSSH..",
    "..BBBBBB..",
    ".BBBBBBBB.",
    ".BBBBBBBB.",
    "AA.BBBB.AA",
    "..BB..BB..",
]

# Arms drawn in closer -- alternate typing-motion frame.
FRAME_WORK2 = [
    ".HHHHHH...",
    "HHHHHHHH..",
    "HSSSSSSSH.",
    "HSSESSESH.",
    "HSSSSSSSH.",
    "HSSMMMSSH.",
    ".HSSSSSH..",
    "..BBBBBB..",
    ".BBBBBBBB.",
    ".BBBBBBBB.",
    ".AABBBBAA.",
    "..BB..BB..",
]

# One hand raised above the shoulder -- Asking pose.
FRAME_ASK = [
    ".HHHHHH...",
    "HHHHHHHH..",
    "HSSSSSSSH.",
    "HSSESSESH.",
    "HSSSSSSSH.",
    "HSSMMMSSHA",
    ".HSSSSSH.A",
    "..BBBBBB..",
    ".BBBBBBBB.",
    ".BBBBBBBB.",
    "AA.BBBB...",
    "..BB..BB..",
]

# X eyes -- Error pose.
FRAME_ERROR = [
    ".HHHHHH...",
    "HHHHHHHH..",
    "HSSSSSSSH.",
    "HSSXSSXSH.",
    "HSSSSSSSH.",
    "HSSMMMSSH.",
    ".HSSSSSH..",
    "..BBBBBB..",
    ".BBBBBBBB.",
    ".BBBBBBBB.",
    "AA.BBBB.AA",
    "..BB..BB..",
]

_ALL_FRAMES = {
    "base": FRAME_BASE,
    "side_eye": FRAME_SIDE_EYE,
    "work2": FRAME_WORK2,
    "ask": FRAME_ASK,
    "error": FRAME_ERROR,
}
for _name, _frame in _ALL_FRAMES.items():
    assert len(_frame) == HEIGHT, f"frame {_name} has {len(_frame)} rows, expected {HEIGHT}"
    for _row in _frame:
        assert len(_row) == WIDTH, f"frame {_name} row {_row!r} has wrong width"

_STATE_FRAME_SEQUENCE = {
    STATE_IDLE: ["base", "base", "base", "side_eye"],
    STATE_WORKING: ["base", "work2"],
    STATE_ASKING: ["ask"],
    STATE_ERROR: ["error"],
}
_STATE_FRAME_INTERVAL = {
    STATE_IDLE: 0.9,
    STATE_WORKING: 0.25,
    STATE_ASKING: 0.6,
    STATE_ERROR: 0.6,
}


def frame_name_for(state: str, anim_tick: float) -> str:
    sequence = _STATE_FRAME_SEQUENCE.get(state, _STATE_FRAME_SEQUENCE[STATE_IDLE])
    interval = _STATE_FRAME_INTERVAL.get(state, 0.9)
    index = int(anim_tick / interval) % len(sequence)
    return sequence[index]


@lru_cache(maxsize=None)
def _render_frame(frame_name: str) -> pygame.Surface:
    grid = _ALL_FRAMES[frame_name]
    surf = pygame.Surface((WIDTH * PIXEL_SCALE, HEIGHT * PIXEL_SCALE), pygame.SRCALPHA)
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            color = _BASE_PALETTE.get(ch)
            if color is None:
                continue
            surf.fill(color, (x * PIXEL_SCALE, y * PIXEL_SCALE, PIXEL_SCALE, PIXEL_SCALE))
    return surf


def get_sprite_surface(state: str, anim_tick: float) -> pygame.Surface:
    frame_name = frame_name_for(state, anim_tick)
    return _render_frame(frame_name)


def get_icon_surface() -> pygame.Surface:
    """Window/taskbar icon -- the same idle mascot frame used for avatars."""
    return _render_frame("base")


def sprite_size() -> tuple[int, int]:
    return WIDTH * PIXEL_SCALE, HEIGHT * PIXEL_SCALE

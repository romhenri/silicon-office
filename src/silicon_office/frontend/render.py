"""Drawing functions: office background, desks, avatars, and animated
overlays (spawn/despawn fade, Asking pulse). Pure functions operating on
already-computed inputs -- no networking/queue logic here, that lives in
main.py, so drawing stays easy to reason about on its own.
"""

from __future__ import annotations

import math

import pygame

from silicon_office.common.constants import STATE_ASKING, STATE_WORKING
from silicon_office.frontend import sprites
from silicon_office.frontend.theme import (
    BANNER_COLOR,
    DESK_COLOR,
    DESK_TOP_COLOR,
    DISCONNECTED_OVERLAY,
    FLOOR_COLOR_A,
    FLOOR_COLOR_B,
    PAPER_COLOR,
    PAPER_LINE_COLOR,
    PIXEL_SCALE,
    SUBTEXT_COLOR,
    TEXT_COLOR,
    USAGE_BAR_BG_COLOR,
    USAGE_BAR_BORDER_COLOR,
    USAGE_BAR_HEIGHT,
    USAGE_LABEL_COLOR,
    USAGE_TEXT_COLOR,
    color_for_state,
)
from silicon_office.frontend.usage import PRO_SESSION_CAP_USD, PRO_WEEK_CAP_USD, UsageSnapshot

_TILE_SIZE = 48
_background_cache: dict[tuple[int, int], pygame.Surface] = {}


class TextCache:
    """Re-renders font.render() only when (text, color) actually changes --
    font rendering is comparatively expensive, and most fields change rarely
    (project name) while action_label changes on every transition."""

    def __init__(self, font: pygame.font.Font) -> None:
        self._font = font
        self._cache: dict[tuple, tuple[str, tuple, pygame.Surface]] = {}

    def get(self, key: tuple, text: str, color: tuple[int, int, int]) -> pygame.Surface:
        cached = self._cache.get(key)
        if cached is not None and cached[0] == text and cached[1] == color:
            return cached[2]
        surface = self._font.render(text, True, color)
        self._cache[key] = (text, color, surface)
        return surface


def draw_background(screen: pygame.Surface, size: tuple[int, int]) -> None:
    cached = _background_cache.get(size)
    if cached is None:
        cached = pygame.Surface(size)
        for ty in range(0, size[1], _TILE_SIZE):
            for tx in range(0, size[0], _TILE_SIZE):
                even = ((tx // _TILE_SIZE) + (ty // _TILE_SIZE)) % 2 == 0
                cached.fill(FLOOR_COLOR_A if even else FLOOR_COLOR_B, (tx, ty, _TILE_SIZE, _TILE_SIZE))
        _background_cache[size] = cached
    screen.blit(cached, (0, 0))


_PAPER_GAP = 3


def _draw_papers(desk_surface: pygame.Surface, desk_rect_local: pygame.Rect, top_y: int) -> None:
    """Two blocky pixel-art paper sheets, side by side with a 3px gap, sitting
    3px below the hand row (top_y) and centered as a pair on the desk."""
    avail_h = max(1, desk_rect_local.bottom - top_y)
    cell = max(2, min(PIXEL_SCALE, avail_h // 4))
    paper_w = 3 * cell
    paper_h = 4 * cell
    total_w = paper_w * 2 + _PAPER_GAP
    left_x = desk_rect_local.centerx - total_w // 2
    right_x = left_x + paper_w + _PAPER_GAP
    line_h = max(1, cell // 3)

    for paper_x in (left_x, right_x):
        pygame.draw.rect(desk_surface, PAPER_COLOR, (paper_x, top_y, paper_w, paper_h))
        for row in (1, 2, 3):
            ly = top_y + row * cell - line_h // 2
            pygame.draw.rect(
                desk_surface, PAPER_LINE_COLOR, (paper_x + cell // 2, ly, paper_w - cell, line_h)
            )


def draw_agent(
    screen: pygame.Surface,
    rect: pygame.Rect,
    agent: dict,
    anim_tick: float,
    alpha: float,
    highlight_boost: float,
    name_cache: TextCache,
    label_cache: TextCache,
    id_cache: TextCache,
) -> None:
    """Draws one desk + avatar. `alpha` in [0,1] handles spawn/despawn fade.
    `highlight_boost` in [0,1] is the edge-triggered extra flash for the
    first second after entering Asking, layered on top of the steady pulse.
    """
    state = agent.get("state", "idle")
    color = color_for_state(state)

    desk_surface = pygame.Surface(rect.size, pygame.SRCALPHA)
    desk_h = rect.size[1] // 3
    desk_rect_local = pygame.Rect(0, rect.size[1] - desk_h, rect.size[0], desk_h)

    sprite = sprites.get_sprite_surface(state, anim_tick)
    sw, sh = sprite.get_size()
    sprite_x = (rect.width - sw) // 2
    sprite_y = desk_rect_local.top - sh + 10

    if state == STATE_ASKING:
        pulse = 0.5 + 0.5 * abs(math.sin(anim_tick * 4.0))
        radius = int(max(sw, sh) * 0.62 + pulse * 10 + highlight_boost * 14)
        ring_alpha = min(255, int(120 + pulse * 100 + highlight_boost * 35))
        ring_surface = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.circle(
            ring_surface,
            (*color, ring_alpha),
            (rect.width // 2, sprite_y + sh // 2),
            radius,
            width=4,
        )
        desk_surface.blit(ring_surface, (0, 0))

    desk_surface.blit(sprite, (sprite_x, sprite_y))

    # Desk is drawn after the sprite so it overlaps the employee's lower
    # body, like a desk in front of a seated character.
    pygame.draw.rect(desk_surface, DESK_COLOR, desk_rect_local, border_radius=4)
    pygame.draw.rect(desk_surface, DESK_TOP_COLOR, desk_rect_local, width=3, border_radius=4)

    if state in (STATE_WORKING, STATE_ASKING):
        hand_y = sprites.HAND_ROW_INDEX * PIXEL_SCALE
        hand_bottom = sprite_y + hand_y + PIXEL_SCALE
        _draw_papers(desk_surface, desk_rect_local, hand_bottom + _PAPER_GAP)
        hands = sprite.subsurface((0, hand_y, sw, PIXEL_SCALE))
        desk_surface.blit(hands, (sprite_x, sprite_y + hand_y))

    # Status light: a small square base topped by a circle bulb, like a
    # street light, planted at the back edge of the desk so it stands up
    # off the table surface instead of sitting flat on it.
    badge_radius = min(10, max(5, desk_h // 3))
    badge_x = desk_rect_local.right - badge_radius - 4
    badge_square = pygame.Rect(0, 0, badge_radius * 2, badge_radius * 2)
    badge_square.midbottom = (badge_x, desk_rect_local.top)
    pygame.draw.rect(desk_surface, color, badge_square)
    pygame.draw.circle(desk_surface, color, badge_square.midtop, badge_radius)

    clamped_alpha = max(0.0, min(1.0, alpha))
    if clamped_alpha < 1.0:
        desk_surface.set_alpha(int(255 * clamped_alpha))
    screen.blit(desk_surface, rect.topleft)

    session_id = agent.get("session_id", "")
    name_surf = name_cache.get((session_id, "name"), agent.get("project_name", "?"), TEXT_COLOR)
    label_surf = label_cache.get((session_id, "label"), agent.get("action_label", ""), color)
    id_surf = id_cache.get((session_id, "id"), session_id[:8], SUBTEXT_COLOR)

    text_y = rect.bottom - 4
    for surf in (id_surf, label_surf, name_surf):
        if clamped_alpha < 1.0:
            surf = surf.copy()
            surf.set_alpha(int(255 * clamped_alpha))
        tx = rect.left + (rect.width - surf.get_width()) // 2
        text_y -= surf.get_height() + 2
        screen.blit(surf, (tx, text_y))


def draw_connection_banner(
    screen: pygame.Surface, font: pygame.font.Font, window_size: tuple[int, int]
) -> None:
    overlay = pygame.Surface(window_size, pygame.SRCALPHA)
    overlay.fill(DISCONNECTED_OVERLAY)
    screen.blit(overlay, (0, 0))
    text = font.render("Reconnecting to daemon...", True, BANNER_COLOR)
    screen.blit(text, ((window_size[0] - text.get_width()) // 2, 12))


def _format_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


def _blit_stat(
    screen: pygame.Surface, font: pygame.font.Font, label: str, stat: str, x: int, center_y: int
) -> int:
    """Blits `label` then `stat` starting at x; returns the x just past the end."""
    label_surf = font.render(f"{label}  ", True, USAGE_LABEL_COLOR)
    stat_surf = font.render(stat, True, USAGE_TEXT_COLOR)
    screen.blit(label_surf, (x, center_y - label_surf.get_height() // 2))
    x += label_surf.get_width()
    screen.blit(stat_surf, (x, center_y - stat_surf.get_height() // 2))
    return x + stat_surf.get_width()


def draw_usage_bar(
    screen: pygame.Surface, font: pygame.font.Font, window_size: tuple[int, int], usage: UsageSnapshot
) -> None:
    """NOT the account's real plan-quota usage shown on claude.ai (that
    figure is server-side and has no local source this app can read).
    Computed from transcript token counts x published API pricing, then
    expressed as a % of hand-set, unverified Pro-plan cap estimates
    (PRO_SESSION_CAP_USD, PRO_WEEK_CAP_USD): local spend in the trailing
    5-hour session window vs. the trailing 7-day week window."""
    w, _ = window_size
    bar_rect = pygame.Rect(0, 0, w, USAGE_BAR_HEIGHT)
    pygame.draw.rect(screen, USAGE_BAR_BG_COLOR, bar_rect)
    pygame.draw.line(screen, USAGE_BAR_BORDER_COLOR, (0, USAGE_BAR_HEIGHT - 1), (w, USAGE_BAR_HEIGHT - 1))

    pad = 16
    center_y = USAGE_BAR_HEIGHT // 2
    # Clamped to [0, 100]: this is a "% of cap used" gauge, not a raw ratio --
    # spend beyond the (unverified) cap estimate still reads as fully used.
    session_pct = min(usage.session_cost / PRO_SESSION_CAP_USD * 100, 100.0)
    week_pct = min(usage.week_cost / PRO_WEEK_CAP_USD * 100, 100.0)
    session_stat = f"{session_pct:.1f}%"
    week_stat = f"{week_pct:.1f}%"

    _blit_stat(screen, font, "Session %", session_stat, pad, center_y)

    week_label = "Week %"
    week_width = font.size(f"{week_label}  ")[0] + font.size(week_stat)[0]
    _blit_stat(screen, font, week_label, week_stat, w - pad - week_width, center_y)

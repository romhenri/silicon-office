"""Real usage stats sourced from Claude Code's own transcript files under
~/.claude/projects/**/<session_id>.jsonl -- these carry per-message token
usage, so cost is computed from actual API usage rather than estimated.

Scanning and JSON-parsing every transcript line on every frame would blow
the <3% CPU budget (RNF-01), so a background thread rescans on a timer and
caches each file's per-line (timestamp, cost, tokens) entries (keyed by
mtime+size); the render loop only ever reads the last computed snapshot.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from silicon_office.common.pricing import cost_for_usage

REFRESH_INTERVAL_SECONDS = 20.0
SESSION_WINDOW_SECONDS = 5 * 3600.0
_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# The weekly quota doesn't roll on a trailing 7-day window -- it resets on a
# fixed local weekday/hour (shown in Claude's own usage panel as e.g.
# "Resets Thu, 06:00"). Monday=0 .. Sunday=6. Adjust these two if your
# account's reset schedule differs.
WEEK_RESET_WEEKDAY = 3  # Thursday
WEEK_RESET_HOUR = 6

# Anthropic doesn't expose the account's real plan-quota usage locally, so
# these are rough, hand-set estimates of the Pro plan's 5-hour session cap
# and weekly cap (in local-est. dollars) used only to turn the scanned
# transcript cost into an approximate "% of cap" for the two top-bar
# metrics. Adjust these if your plan or observed caps differ.
PRO_SESSION_CAP_USD = 20.0
PRO_WEEK_CAP_USD = 100.0


def _week_window_start(now: float) -> float:
    """Epoch of the most recent weekly quota reset (local time)."""
    local_now = datetime.fromtimestamp(now)
    candidate = local_now.replace(hour=WEEK_RESET_HOUR, minute=0, second=0, microsecond=0)
    candidate -= timedelta(days=(candidate.weekday() - WEEK_RESET_WEEKDAY) % 7)
    if candidate > local_now:
        candidate -= timedelta(days=7)
    return candidate.timestamp()


@dataclass
class UsageSnapshot:
    session_cost: float = 0.0
    session_tokens: int = 0
    week_cost: float = 0.0
    week_tokens: int = 0


@dataclass
class _FileUsage:
    mtime: float
    size: int
    entries: list[tuple[float, float, int]] = field(default_factory=list)


def _parse_ts(ts: object) -> float:
    if not isinstance(ts, str):
        return 0.0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _scan_file(path: Path) -> list[tuple[float, float, int]]:
    """Per-line (timestamp, cost, tokens) for every usage-bearing record --
    a session's transcript file can be resumed and appended to long after it
    was first created, so windowing must key off each line's own timestamp
    rather than the file's mtime."""
    entries: list[tuple[float, float, int]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                message = record.get("message")
                if not isinstance(message, dict):
                    continue
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue
                model = message.get("model", "")
                cost = cost_for_usage(model, usage)
                tokens = (
                    (usage.get("input_tokens") or 0)
                    + (usage.get("output_tokens") or 0)
                    + (usage.get("cache_creation_input_tokens") or 0)
                    + (usage.get("cache_read_input_tokens") or 0)
                )
                entries.append((_parse_ts(record.get("timestamp")), cost, tokens))
    except OSError:
        pass
    return entries


class UsageTracker:
    """Scans transcripts on a timer in a background thread; `snapshot()` is
    the only method the render loop calls, and it never touches disk."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._file_cache: dict[Path, _FileUsage] = {}
        self._session_cost = 0.0
        self._session_tokens = 0
        self._week_cost = 0.0
        self._week_tokens = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._refresh()
            except Exception:
                pass
            self._stop.wait(REFRESH_INTERVAL_SECONDS)

    def _refresh(self) -> None:
        if not _PROJECTS_DIR.is_dir():
            return
        now = time.time()
        session_cutoff = now - SESSION_WINDOW_SECONDS
        week_cutoff = _week_window_start(now)
        session_cost = 0.0
        session_tokens = 0
        week_cost = 0.0
        week_tokens = 0
        fresh_cache: dict[Path, _FileUsage] = {}

        for path in _PROJECTS_DIR.rglob("*.jsonl"):
            try:
                stat = path.stat()
            except OSError:
                continue
            cached = self._file_cache.get(path)
            if cached is not None and cached.mtime == stat.st_mtime and cached.size == stat.st_size:
                usage = cached
            else:
                entries = _scan_file(path)
                usage = _FileUsage(stat.st_mtime, stat.st_size, entries)
            fresh_cache[path] = usage
            for ts, cost, tokens in usage.entries:
                if ts >= week_cutoff:
                    week_cost += cost
                    week_tokens += tokens
                if ts >= session_cutoff:
                    session_cost += cost
                    session_tokens += tokens

        with self._lock:
            self._file_cache = fresh_cache
            self._session_cost = session_cost
            self._session_tokens = session_tokens
            self._week_cost = week_cost
            self._week_tokens = week_tokens

    def snapshot(self) -> UsageSnapshot:
        with self._lock:
            return UsageSnapshot(
                session_cost=self._session_cost,
                session_tokens=self._session_tokens,
                week_cost=self._week_cost,
                week_tokens=self._week_tokens,
            )

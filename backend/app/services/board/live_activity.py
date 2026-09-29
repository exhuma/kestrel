"""What this kestrel process is doing for each request right now
(feature 033, FR-003).

The board's stored state cannot say whether anything is *running*: a
claimed card may belong to a turn that crashed, and some work — the
coordinator's turn, input screening — leaves no card state at all
while it runs. So "working" comes only from here: an in-memory record
of turns in flight, entered and left around the work itself. A
restart empties it, which is exactly right — nothing survives a
restart that could still be running.
"""
from __future__ import annotations

import itertools
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol

from app.backends.base import TurnStopped

#: Told a tool's name each time the agent calls one (feature 036).
NoteTool = Callable[[str], None]

#: Live views are told about tool calls at most this often per turn, so a
#: model calling a tool every second does not flood them (FR-005).
ANNOUNCE_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class LiveTurn:
    """One piece of work in flight.

    :param actor: Who is working — a specialist's label, or
        ``"coordinator"`` / ``"screening"``.
    :param subject: What on — a card title, when there is one.
    :param started_at: When it started (UTC).
    :param tool: The last tool the agent called, if any (feature 036).
    :param tool_calls: How many tool calls the turn has made so far.
    """

    actor: str
    subject: str | None
    started_at: datetime
    tool: str | None = None
    tool_calls: int = 0


class LiveActivity:
    """Turns in flight, per workflow."""

    def __init__(self) -> None:
        self._turns: dict[str, dict[int, LiveTurn]] = {}
        self._ids = itertools.count()

    @contextmanager
    def track(
        self,
        workflow_id: str,
        actor: str,
        subject: str | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> Iterator[NoteTool]:
        """Record work on *workflow_id* for as long as the block runs —
        however it ends. Yields a callable to note each tool call; live
        views are told through *on_change*, throttled."""
        key = next(self._ids)
        turns = self._turns.setdefault(workflow_id, {})
        turns[key] = LiveTurn(actor, subject, datetime.now(timezone.utc))
        last_told = [float("-inf")]

        def note_tool(tool: str) -> None:
            turn = turns.get(key)
            if turn is None:
                return
            turns[key] = replace(
                turn, tool=tool, tool_calls=turn.tool_calls + 1
            )
            now = time.monotonic()
            if on_change is not None and (
                now - last_told[0] >= ANNOUNCE_INTERVAL_SECONDS
            ):
                last_told[0] = now
                on_change()

        try:
            yield note_tool
        finally:
            turns.pop(key, None)
            if not turns:
                self._turns.pop(workflow_id, None)

    def current(self, workflow_id: str) -> LiveTurn | None:
        """The longest-running turn on *workflow_id*, or ``None``."""
        turns = self._turns.get(workflow_id)
        if not turns:
            return None
        return min(turns.values(), key=lambda t: t.started_at)


def _ignore_tool(_tool: str) -> None:
    """The tool note of work nobody records."""


def tracking(
    live: LiveActivity | None,
    workflow_id: str,
    actor: str,
    subject: str | None = None,
    on_change: Callable[[], None] | None = None,
) -> AbstractContextManager[NoteTool]:
    """:meth:`LiveActivity.track` when there is a registry to record in,
    else a no-op — callers built without one (most tests) need no
    branching of their own."""
    if live is None:
        return nullcontext(_ignore_tool)
    return live.track(workflow_id, actor, subject, on_change)


class _Announces(Protocol):
    def announce(self, workflow_id: str) -> None: ...


def announcer(
    board: _Announces | None, workflow_id: str
) -> Callable[[], None] | None:
    """Tell live views *workflow_id* changed, through *board*, if any."""
    if board is None:
        return None
    return lambda: board.announce(workflow_id)


def turn_failure(actor: str, error: Exception) -> str:
    """A short, safe reason for a failed turn — never the backend's own
    error text, which may carry anything. A turn kestrel stopped itself
    carries its own safe reason (feature 036)."""
    stopped = _stopped(error)
    if stopped is not None:
        return f"{actor}'s turn was stopped: {stopped.reason}"
    if "timed out" in str(error):
        return f"{actor}'s turn timed out"
    return f"{actor}'s turn failed; see the kestrel log"


def _stopped(error: BaseException | None) -> TurnStopped | None:
    """The :class:`TurnStopped` behind *error*, however it was wrapped."""
    while error is not None:
        if isinstance(error, TurnStopped):
            return error
        error = error.__cause__
    return None


@lru_cache
def get_live_activity() -> LiveActivity:
    """Return the process-wide live-activity registry."""
    return LiveActivity()

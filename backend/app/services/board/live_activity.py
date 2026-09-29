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
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache


@dataclass(frozen=True)
class LiveTurn:
    """One piece of work in flight.

    :param actor: Who is working — a specialist's label, or
        ``"coordinator"`` / ``"screening"``.
    :param subject: What on — a card title, when there is one.
    :param started_at: When it started (UTC).
    """

    actor: str
    subject: str | None
    started_at: datetime


class LiveActivity:
    """Turns in flight, per workflow."""

    def __init__(self) -> None:
        self._turns: dict[str, dict[int, LiveTurn]] = {}
        self._ids = itertools.count()

    @contextmanager
    def track(
        self, workflow_id: str, actor: str, subject: str | None = None
    ) -> Iterator[None]:
        """Record work on *workflow_id* for as long as the block runs —
        however it ends."""
        key = next(self._ids)
        turns = self._turns.setdefault(workflow_id, {})
        turns[key] = LiveTurn(actor, subject, datetime.now(timezone.utc))
        try:
            yield
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


def tracking(
    live: LiveActivity | None,
    workflow_id: str,
    actor: str,
    subject: str | None = None,
) -> AbstractContextManager[None]:
    """:meth:`LiveActivity.track` when there is a registry to record in,
    else a no-op — callers built without one (most tests) need no
    branching of their own."""
    if live is None:
        return nullcontext()
    return live.track(workflow_id, actor, subject)


def turn_failure(actor: str, error: Exception) -> str:
    """A short, safe reason for a failed turn — never the backend's own
    error text, which may carry anything."""
    if "timed out" in str(error):
        return f"{actor}'s turn timed out"
    return f"{actor}'s turn failed; see the kestrel log"


@lru_cache
def get_live_activity() -> LiveActivity:
    """Return the process-wide live-activity registry."""
    return LiveActivity()

"""How long an agent turn may run: as long as it keeps working.

A turn is stopped when its agent has shown no activity (a tool call, a
streamed message or reasoning part, a stream-json line) for
``idle_seconds``, or when it has run for ``max_seconds`` in all. A coder
busy for hours keeps going; one that hangs is stopped within the idle
limit. Looping turns are stopped earlier still, by the tool budget
(``opencode_tools.ToolLoopGuard``).

Harness-neutral: a backend only has to call ``TurnRequest.on_activity``
when its agent does something.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import TypeVar

from app.backends.base import TurnRequest

T = TypeVar("T")

_log = logging.getLogger("kestrel.board.turns")
_MINUTE = 60


@dataclass(frozen=True)
class TurnLimits:
    """A turn's idle limit and overall ceiling, in seconds."""

    idle_seconds: float
    max_seconds: float

    @classmethod
    def within(cls, seconds: float) -> TurnLimits:
        """One limit for both: a turn must finish within *seconds*."""
        return cls(seconds, seconds)


class TurnLimitReached(TimeoutError):
    """A turn was stopped by its limits.

    :param reason: What happened, in words for the operator ("made no
        progress for 15 minutes").
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"turn stopped: {reason}")
        self.reason = reason


class _Activity:
    """When the agent last did something."""

    def __init__(self) -> None:
        self.last = time.monotonic()

    def touch(self, *_args: object) -> None:
        self.last = time.monotonic()


def watched(request: TurnRequest) -> tuple[TurnRequest, _Activity]:
    """*request*, reporting activity to a fresh watch as well as to its
    own callbacks; and that watch."""
    activity = _Activity()
    own_activity, own_tool = request.on_activity, request.on_tool

    def on_activity() -> None:
        activity.touch()
        if own_activity is not None:
            own_activity()

    def on_tool(tool: str) -> None:
        activity.touch()
        if own_tool is not None:
            own_tool(tool)

    return replace(request, on_activity=on_activity, on_tool=on_tool), activity


async def within_limits(
    turn: Awaitable[T], activity: _Activity, limits: TurnLimits
) -> T:
    """Await *turn* while it stays active and under its ceiling.

    :raises TurnLimitReached: After cancelling the turn, when it was idle
        for ``limits.idle_seconds`` or ran past ``limits.max_seconds``.
    """
    task = asyncio.ensure_future(turn)
    started = time.monotonic()
    while True:
        now = time.monotonic()
        idle_left = limits.idle_seconds - (now - activity.last)
        total_left = limits.max_seconds - (now - started)
        done, _ = await asyncio.wait({task}, timeout=max(
            min(idle_left, total_left), 0
        ))
        if done:
            return task.result()
        now = time.monotonic()
        if now - started >= limits.max_seconds:
            await _stop(task)
            raise TurnLimitReached(
                f"ran past its limit of {_minutes(limits.max_seconds)}"
            )
        if now - activity.last >= limits.idle_seconds:
            await _stop(task)
            raise TurnLimitReached(
                f"made no progress for {_minutes(limits.idle_seconds)}"
            )


async def _stop(task: asyncio.Future) -> None:
    """Cancel the turn and let it clean up (opencode aborts its session).
    How it ends after that no longer matters: the limit decided."""
    task.cancel()
    try:
        with suppress(asyncio.CancelledError):
            await task
    except Exception:
        _log.debug("a stopped turn ended with an error", exc_info=True)


def _minutes(seconds: float) -> str:
    if seconds < _MINUTE:
        return f"{seconds:g} seconds"
    minutes = seconds / _MINUTE
    return f"{minutes:g} minute{'s' if minutes != 1 else ''}"

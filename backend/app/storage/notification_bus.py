"""Process-wide pub/sub for the notification center.

Notifications are global (not per-workflow), so this bus is keyless: a
publish is a tick telling every subscriber "the notification list
changed, re-read it". The SSE route re-serialises the current list on
each tick, replacing the old fixed-interval poll.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache


class NotificationBus:
    """Broadcasts change ticks to notification-center subscribers."""

    def __init__(self) -> None:
        self._subs: list[asyncio.Queue[int]] = []

    def subscribe(self) -> asyncio.Queue[int]:
        """Register and return a new subscriber queue."""
        q: asyncio.Queue[int] = asyncio.Queue()
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[int]) -> None:
        """Remove a subscriber queue if present."""
        if q in self._subs:
            self._subs.remove(q)

    def publish(self) -> None:
        """Notify every live subscriber that the list changed."""
        for q in self._subs:
            q.put_nowait(1)


@lru_cache
def get_notification_bus() -> NotificationBus:
    """Return the process-wide NotificationBus singleton."""
    return NotificationBus()

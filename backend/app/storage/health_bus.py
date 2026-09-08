"""Process-wide pub/sub for source health status (feature 014).

Health is global, not per-workflow — like the notification center's own
bus (``notification_bus.py``), this bus is keyless: a publish is a tick
telling every subscriber "some entry's status changed, re-read the
list". The SSE route re-serialises the current list on each tick.
"""
from __future__ import annotations

import asyncio


class HealthBus:
    """Broadcasts change ticks to source-health subscribers."""

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

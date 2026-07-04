"""Per-workflow pub/sub for pushing state changes to SSE subscribers.

Mirrors the session registry's fan-out (see ``storage/registry.py``),
but carries no payload: a publish is only a *tick* telling subscribers
"this run changed, re-read it". The SSE route re-serialises the current
detail on each tick, so a subscriber always sees the latest snapshot and
can never drift out of order with the store.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache


class WorkflowBus:
    """Broadcasts change ticks to per-workflow subscribers."""

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[str]]] = {}

    def subscribe(self, workflow_id: str) -> asyncio.Queue[str]:
        """
        Register and return a new subscriber queue for a workflow.

        :param workflow_id: The run to subscribe to.
        :returns: A queue that receives the workflow id on every change.
        """
        q: asyncio.Queue[str] = asyncio.Queue()
        self._subs.setdefault(workflow_id, []).append(q)
        return q

    def unsubscribe(
        self, workflow_id: str, q: asyncio.Queue[str]
    ) -> None:
        """Remove a subscriber queue if present."""
        subs = self._subs.get(workflow_id, [])
        if q in subs:
            subs.remove(q)

    def publish(self, workflow_id: str) -> None:
        """Notify every live subscriber that a run changed."""
        for q in self._subs.get(workflow_id, []):
            q.put_nowait(workflow_id)


@lru_cache
def get_workflow_bus() -> WorkflowBus:
    """Return the process-wide WorkflowBus singleton."""
    return WorkflowBus()

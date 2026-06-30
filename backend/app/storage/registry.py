"""In-memory registry of sessions with per-session pub/sub."""
from __future__ import annotations

import asyncio
from functools import lru_cache

from app.models import ParsedEvent, SessionRecord


class SessionRegistry:
    """Stores session records and broadcasts events to subscribers."""

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._subs: dict[str, list[asyncio.Queue[ParsedEvent]]] = {}

    def create(self, session_id: str, cwd: str) -> SessionRecord:
        """Create and store a new running session record."""
        record = SessionRecord(session_id=session_id, cwd=cwd)
        self._records[session_id] = record
        self._subs.setdefault(session_id, [])
        return record

    def get(self, session_id: str) -> SessionRecord | None:
        """Return the record for a session id, or None."""
        return self._records.get(session_id)

    def list(self) -> list[SessionRecord]:
        """Return all session records in insertion order."""
        return list(self._records.values())

    def append_event(
        self, session_id: str, event: ParsedEvent
    ) -> None:
        """Append an event and notify all live subscribers."""
        record = self._records.get(session_id)
        if record is None:
            return
        record.events.append(event)
        for q in self._subs.get(session_id, []):
            q.put_nowait(event)

    def set_status(self, session_id: str, status: str) -> None:
        """Update the status of an existing session record."""
        record = self._records.get(session_id)
        if record is not None:
            record.status = status

    def subscribe(
        self, session_id: str
    ) -> asyncio.Queue[ParsedEvent]:
        """Register and return a new subscriber queue."""
        q: asyncio.Queue[ParsedEvent] = asyncio.Queue()
        self._subs.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(
        self, session_id: str, q: asyncio.Queue[ParsedEvent]
    ) -> None:
        """Remove a subscriber queue if present."""
        subs = self._subs.get(session_id, [])
        if q in subs:
            subs.remove(q)


@lru_cache
def get_registry() -> SessionRegistry:
    """Return the process-wide SessionRegistry singleton."""
    return SessionRegistry()

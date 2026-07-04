"""In-memory registry of sessions with per-session pub/sub."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import lru_cache

from app.models import CanonicalEvent, EventKind, SessionRecord
from app.persistence.store import SessionStore, get_store


class SessionRegistry:
    """Stores session records and broadcasts events to subscribers."""

    def __init__(
        self, store: SessionStore | None = None
    ) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._subs: dict[
            str, list[asyncio.Queue[CanonicalEvent]]
        ] = {}
        self._store = store

    def create(self, session_id: str, cwd: str) -> SessionRecord:
        """
        Create and store a new running session record.

        :param session_id: Unique id of the session.
        :param cwd: Working directory the session runs in.
        :returns: The newly created session record.
        """
        record = SessionRecord(
            session_id=session_id, cwd=cwd,
            created_at=datetime.now(timezone.utc),
        )
        self._records[session_id] = record
        self._subs.setdefault(session_id, [])
        if self._store is not None:
            self._store.save_session(record)
        return record

    def get(self, session_id: str) -> SessionRecord | None:
        """
        Return the record for a session id, or None.

        :param session_id: Unique id of the session.
        :returns: The session record, or None if not found.
        """
        return self._records.get(session_id)

    def list(self) -> list[SessionRecord]:
        """
        Return all session records in insertion order.

        :returns: All session records.
        """
        return list(self._records.values())

    def append_event(
        self, session_id: str, event: CanonicalEvent
    ) -> None:
        """
        Append an event and notify all live subscribers.

        A terminal ``RESULT`` event flips the session to ``idle`` — the
        backend-agnostic replacement for the old claude-specific
        ``type == "result"`` check.

        :param session_id: Unique id of the session.
        :param event: The canonical event to append.
        """
        record = self._records.get(session_id)
        if record is None:
            return
        record.events.append(event)
        for q in self._subs.get(session_id, []):
            q.put_nowait(event)
        if self._store is not None:
            self._store.append_event(session_id, event)
        if event.kind == EventKind.RESULT:
            self.set_status(session_id, "idle")

    def remove(self, session_id: str) -> None:
        """
        Drop a session record, its subscribers, and its persisted rows.

        The write-through counterpart to :meth:`create`.

        :param session_id: Unique id of the session to remove.
        """
        self._records.pop(session_id, None)
        self._subs.pop(session_id, None)
        if self._store is not None:
            self._store.delete(session_id)

    def set_status(self, session_id: str, status: str) -> None:
        """
        Update the status of an existing session record.

        :param session_id: Unique id of the session.
        :param status: The new status value.
        """
        record = self._records.get(session_id)
        if record is not None:
            record.status = status
            if self._store is not None:
                self._store.set_status(session_id, status)

    def preload(
        self, records: list[SessionRecord]
    ) -> None:
        """
        Seed the registry with persisted records.

        Does not write back to the store.

        :param records: Records loaded from persistence.
        """
        for record in records:
            self._records[record.session_id] = record
            self._subs.setdefault(record.session_id, [])

    def subscribe(
        self, session_id: str
    ) -> asyncio.Queue[CanonicalEvent]:
        """
        Register and return a new subscriber queue.

        :param session_id: Unique id of the session.
        :returns: A new asyncio queue for this subscriber.
        """
        q: asyncio.Queue[CanonicalEvent] = asyncio.Queue()
        self._subs.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(
        self, session_id: str, q: asyncio.Queue[CanonicalEvent]
    ) -> None:
        """
        Remove a subscriber queue if present.

        :param session_id: Unique id of the session.
        :param q: The queue to remove.
        """
        subs = self._subs.get(session_id, [])
        if q in subs:
            subs.remove(q)


@lru_cache
def get_registry() -> SessionRegistry:
    """
    Return the process-wide SessionRegistry singleton.

    Preloads all persisted sessions so history survives
    restarts. Requires migrations to have been applied
    (``uv run alembic upgrade head``).

    :returns: The cached session registry instance.
    """
    store = get_store()
    registry = SessionRegistry(store=store)
    registry.preload(store.load_all())
    return registry

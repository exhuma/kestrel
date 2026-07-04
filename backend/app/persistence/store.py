"""Write-through persistence for session records."""
from __future__ import annotations

import json
from dataclasses import asdict
from functools import lru_cache

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    CanonicalEvent,
    EventKind,
    SessionRecord,
    map_claude_dict,
)
from app.persistence.db import get_sessionmaker
from app.persistence.tables import EventRow, SessionRow


def _event_to_json(event: CanonicalEvent) -> dict[str, object]:
    """Serialise a canonical event to a JSON-ready dict."""
    data = asdict(event)
    data["kind"] = event.kind.value
    return data


def _event_from_json(
    data: dict[str, object], session_id: str
) -> CanonicalEvent:
    """
    Rebuild a canonical event from a stored JSON payload.

    Rows written before the canonical-event migration hold a raw claude
    stream-json object (no ``kind``/``native`` keys); those are mapped
    on read so existing session history survives the upgrade.
    """
    if "kind" in data and "native" in data:
        fields = dict(data)
        fields["kind"] = EventKind(fields["kind"])
        fields["session_id"] = session_id
        return CanonicalEvent(**fields)  # type: ignore[arg-type]
    legacy = map_claude_dict(data)
    if legacy is None:
        return CanonicalEvent(
            kind=EventKind.UNKNOWN, session_id=session_id, native=data
        )
    legacy.session_id = session_id
    return legacy


class SessionStore:
    """Persists session records and events to the database."""

    def __init__(
        self, factory: sessionmaker[Session]
    ) -> None:
        self._factory = factory

    def save_session(self, record: SessionRecord) -> None:
        """
        Insert a new session row.

        :param record: The freshly created session record.
        """
        with self._factory.begin() as db:
            db.add(
                SessionRow(
                    session_id=record.session_id,
                    cwd=record.cwd,
                    status=record.status,
                    created_at=record.created_at,
                )
            )

    def set_status(
        self, session_id: str, status: str
    ) -> None:
        """
        Update a persisted session's status.

        :param session_id: Unique id of the session.
        :param status: The new status value.
        """
        with self._factory.begin() as db:
            row = db.get(SessionRow, session_id)
            if row is not None:
                row.status = status

    def append_event(
        self, session_id: str, event: CanonicalEvent
    ) -> None:
        """
        Persist one canonical event.

        The ``type`` column stores the event kind; ``raw`` stores the
        full canonical payload (including the original ``native`` blob).

        :param session_id: Unique id of the session.
        :param event: The canonical event to persist.
        """
        with self._factory.begin() as db:
            db.add(
                EventRow(
                    session_id=session_id,
                    type=event.kind.value,
                    raw=json.dumps(_event_to_json(event)),
                )
            )

    def delete(self, session_id: str) -> None:
        """
        Delete a session and its events (events first for the FK).

        :param session_id: Unique id of the session to delete.
        """
        with self._factory.begin() as db:
            db.execute(
                delete(EventRow).where(
                    EventRow.session_id == session_id
                )
            )
            row = db.get(SessionRow, session_id)
            if row is not None:
                db.delete(row)

    def load_all(self) -> list[SessionRecord]:
        """
        Load all sessions with their events, oldest first.

        :returns: Fully hydrated session records.
        """
        with self._factory() as db:
            records: list[SessionRecord] = []
            for row in db.scalars(select(SessionRow)):
                stmt = (
                    select(EventRow)
                    .where(
                        EventRow.session_id == row.session_id
                    )
                    .order_by(EventRow.id)
                )
                events = [
                    _event_from_json(
                        json.loads(e.raw), row.session_id
                    )
                    for e in db.scalars(stmt)
                ]
                records.append(
                    SessionRecord(
                        session_id=row.session_id,
                        cwd=row.cwd,
                        status=row.status,
                        events=events,
                        created_at=row.created_at,
                    )
                )
            return records


@lru_cache
def get_store() -> SessionStore:
    """
    Return the process-wide SessionStore singleton.

    :returns: The cached session store instance.
    """
    return SessionStore(get_sessionmaker())

"""Write-through persistence for session records."""
from __future__ import annotations

import json
from functools import lru_cache

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ParsedEvent, SessionRecord
from app.persistence.db import get_sessionmaker
from app.persistence.tables import EventRow, SessionRow


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
        self, session_id: str, event: ParsedEvent
    ) -> None:
        """
        Persist one parsed event.

        :param session_id: Unique id of the session.
        :param event: The parsed event to persist.
        """
        with self._factory.begin() as db:
            db.add(
                EventRow(
                    session_id=session_id,
                    type=event.type,
                    raw=json.dumps(event.raw),
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
                    ParsedEvent(
                        type=e.type,
                        session_id=row.session_id,
                        raw=json.loads(e.raw),
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

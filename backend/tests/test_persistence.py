"""Tests for the persistence layer and migrations."""
from __future__ import annotations

import json

from sqlalchemy.orm import sessionmaker

from app.models import CanonicalEvent, EventKind
from app.persistence.store import SessionStore
from app.persistence.tables import EventRow, SessionRow
from app.storage.registry import SessionRegistry
from tests.database_support import isolated_engine


def _store() -> SessionStore:
    """Build a store on an isolated, migrated database."""
    return SessionStore(sessionmaker(bind=isolated_engine()))


def test_registry_survives_restart() -> None:
    """Ensure sessions and canonical events persist across registries."""
    store = _store()
    reg = SessionRegistry(store=store)
    reg.create("s1", "/tmp/s1")
    reg.append_event(
        "s1",
        CanonicalEvent(
            kind=EventKind.ASSISTANT_TEXT,
            session_id="s1",
            text="hi",
            native={"n": 1},
        ),
    )
    reg.set_status("s1", "idle")

    fresh = SessionRegistry(store=store)
    fresh.preload(store.load_all())
    rec = fresh.get("s1")
    assert rec is not None
    assert rec.cwd == "/tmp/s1"
    assert rec.status == "idle"
    assert len(rec.events) == 1
    assert rec.events[0].kind is EventKind.ASSISTANT_TEXT
    assert rec.events[0].text == "hi"
    assert rec.events[0].native == {"n": 1}


def test_delete_removes_session_and_events() -> None:
    """Ensure deleting a session drops it and its events from the DB."""
    store = _store()
    reg = SessionRegistry(store=store)
    reg.create("s1", "/tmp/s1")
    reg.append_event(
        "s1", CanonicalEvent(kind=EventKind.ASSISTANT_TEXT, session_id="s1")
    )
    store.delete("s1")
    assert store.load_all() == []


def test_load_upgrades_legacy_claude_event_rows() -> None:
    """Ensure rows written before the canonical migration still load.

    Legacy rows hold a raw claude stream-json object (no ``kind``/
    ``native`` keys); they must be mapped to canonical events on read so
    existing session history survives the upgrade.
    """
    store = _store()
    with store._factory.begin() as db:  # type: ignore[attr-defined]
        db.add(SessionRow(session_id="s1", cwd="/tmp/s1", status="idle"))
        db.add(
            EventRow(
                session_id="s1",
                type="result",
                raw=json.dumps(
                    {
                        "type": "result",
                        "session_id": "s1",
                        "result": "legacy deliverable",
                    }
                ),
            )
        )

    records = store.load_all()
    assert len(records) == 1
    event = records[0].events[0]
    assert event.kind is EventKind.RESULT
    assert event.text == "legacy deliverable"
    assert event.session_id == "s1"

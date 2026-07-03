"""Tests for the in-memory session registry."""
from __future__ import annotations

import asyncio

import pytest

from app.models import ParsedEvent
from app.storage.registry import SessionRegistry


def _event(kind: str = "assistant") -> ParsedEvent:
    return ParsedEvent(type=kind, session_id="s1", raw={})


def test_create_get_list() -> None:
    """Ensure records can be created, fetched, and listed."""
    reg = SessionRegistry()
    rec = reg.create("s1", "/tmp/s1")
    assert rec.status == "running"
    assert reg.get("s1") is rec
    assert reg.get("missing") is None
    assert [r.session_id for r in reg.list()] == ["s1"]


def test_remove_drops_record() -> None:
    """Ensure remove deletes the record and its subscribers."""
    reg = SessionRegistry()
    reg.create("s1", "/tmp/s1")
    reg.remove("s1")
    assert reg.get("s1") is None
    assert reg.list() == []
    reg.remove("s1")  # idempotent — no raise on unknown id


def test_append_event_records_and_sets_status() -> None:
    """Ensure events accumulate and status can change."""
    reg = SessionRegistry()
    reg.create("s1", "/tmp/s1")
    reg.append_event("s1", _event())
    reg.set_status("s1", "idle")
    rec = reg.get("s1")
    assert rec is not None
    assert len(rec.events) == 1
    assert rec.status == "idle"


@pytest.mark.asyncio
async def test_subscribe_receives_appended_events() -> None:
    """Ensure subscribers receive events appended after subscribe."""
    reg = SessionRegistry()
    reg.create("s1", "/tmp/s1")
    q = reg.subscribe("s1")
    reg.append_event("s1", _event("result"))
    received = await asyncio.wait_for(q.get(), timeout=1.0)
    assert received.type == "result"

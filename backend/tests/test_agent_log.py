"""Tests for the ``kestrel.agent`` log: agent output keyed by session id."""
from __future__ import annotations

import json
import logging

import pytest

from app.backends.agent_log import (
    LOGGER_NAME,
    MAX_TEXT,
    AgentLog,
    clip,
    describe,
)
from app.logging_config import JsonFormatter
from app.models import CanonicalEvent, EventKind


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER_NAME]


def test_clip_keeps_short_text_on_one_line() -> None:
    """Ensure short text is only whitespace-collapsed."""
    assert clip("a\n  b\tc") == "a b c"


def test_clip_bounds_long_text_and_counts_the_rest() -> None:
    """Ensure long text is cut and says how much was left out."""
    out = clip("x" * (MAX_TEXT + 40))
    assert out.startswith("x" * MAX_TEXT)
    assert out.endswith("…(+40 chars)")


def test_describe_names_tool_calls() -> None:
    """Ensure a tool call shows its tool and what it acted on."""
    event = CanonicalEvent(
        EventKind.TOOL_USE, "s1", tool_name="Read", tool_summary="a.py"
    )
    assert describe(event) == "tool_use Read a.py"


def test_every_record_carries_session_and_card_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure each level tags the session id (and card id) twice over:
    in the message and as record fields."""
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    log = AgentLog("sess-9", "card-3", "claude")

    log.started()
    log.event(CanonicalEvent(EventKind.ASSISTANT_TEXT, "sess-9", "hi"))
    log.finished("done", duration_ms=12)
    log.finished("boom", is_error=True)
    log.failed("cancelled")

    records = _records(caplog)
    assert [r.levelno for r in records] == [
        logging.INFO, logging.DEBUG, logging.INFO,
        logging.WARNING, logging.WARNING,
    ]
    for record in records:
        assert record.session_id == "sess-9"  # type: ignore[attr-defined]
        assert record.card_id == "card-3"  # type: ignore[attr-defined]
        assert "session=sess-9 card=card-3" in record.getMessage()


def test_events_are_silent_above_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure per-event lines only appear when DEBUG is asked for."""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    AgentLog("s").event(CanonicalEvent(EventKind.ASSISTANT_TEXT, "s", "hi"))
    assert not _records(caplog)


def test_a_huge_agent_message_stays_bounded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure no agent payload can make a log line unbounded."""
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)
    big = "y" * 100_000
    log = AgentLog("s")
    log.event(CanonicalEvent(EventKind.TOOL_RESULT, "s", big))
    log.finished(big)
    assert all(len(r.getMessage()) < 2 * MAX_TEXT for r in _records(caplog))


def test_json_log_has_session_and_card_id_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure the JSON format lifts the ids into top-level fields."""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    AgentLog("sess-1", "card-1").finished("ok")

    doc = json.loads(JsonFormatter().format(_records(caplog)[0]))

    assert doc["logger"] == LOGGER_NAME
    assert doc["session_id"] == "sess-1"
    assert doc["card_id"] == "card-1"


def test_json_log_omits_card_id_when_there_is_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure a turn without a card has no empty card_id field."""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    AgentLog("sess-1").finished("ok")

    doc = json.loads(JsonFormatter().format(_records(caplog)[0]))

    assert "card_id" not in doc

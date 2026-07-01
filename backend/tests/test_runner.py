"""Tests for the session runner argv building and stream consume."""
from __future__ import annotations

from typing import AsyncIterator

import pytest

from app.config import Settings
from app.services.runner import SessionRunner
from app.storage.registry import SessionRegistry


def _runner() -> SessionRunner:
    settings = Settings(
        claude_bin="claude",
        workspace_root="/tmp/ws",
        permission_mode="acceptEdits",
    )
    return SessionRunner(settings, SessionRegistry())


def test_build_argv_start() -> None:
    """Ensure start argv requests stream-json and permission mode."""
    argv = _runner().build_argv("hello")
    assert argv[:3] == ["claude", "-p", "hello"]
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    assert "--permission-mode" in argv
    assert "--resume" not in argv


def test_build_argv_resume() -> None:
    """Ensure resume argv includes the session id."""
    argv = _runner().build_argv("again", resume_id="s9")
    assert "--resume" in argv
    assert argv[argv.index("--resume") + 1] == "s9"


def test_build_argv_appends_model() -> None:
    """Ensure build_argv adds --model when one is given."""
    argv = _runner().build_argv("hi", model="sonnet")
    assert argv[argv.index("--model") + 1] == "sonnet"


def test_build_argv_omits_model_by_default() -> None:
    """Ensure build_argv omits --model when not given."""
    assert "--model" not in _runner().build_argv("hi")


async def _lines(items: list[str]) -> AsyncIterator[str]:
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_consume_creates_record_and_sets_idle() -> None:
    """Ensure consume registers the session and finishes idle."""
    runner = _runner()
    lines = [
        '{"type":"system","subtype":"init","session_id":"s1"}',
        '{"type":"assistant","message":{}}',
        '{"type":"result","subtype":"success","session_id":"s1"}',
    ]
    sid = await runner.consume(_lines(lines), cwd="/tmp/ws/s1")
    assert sid == "s1"
    rec = runner.registry.get("s1")
    assert rec is not None
    assert rec.cwd == "/tmp/ws/s1"
    assert rec.status == "idle"
    assert len(rec.events) == 3


@pytest.mark.asyncio
async def test_consume_resume_appends_to_existing() -> None:
    """Ensure consume with record_id appends to the same record."""
    runner = _runner()
    runner.registry.create("s1", "/tmp/ws/s1")
    lines = [
        '{"type":"assistant","message":{}}',
        '{"type":"result","subtype":"success","session_id":"s1"}',
    ]
    sid = await runner.consume(
        _lines(lines), cwd="/tmp/ws/s1", record_id="s1"
    )
    assert sid == "s1"
    rec = runner.registry.get("s1")
    assert rec is not None
    assert len(rec.events) == 2
    assert rec.status == "idle"

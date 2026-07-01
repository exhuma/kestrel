"""Tests for the session runner argv building and stream consume."""
from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path
from typing import AsyncIterator

import pytest

from app.config import Settings
from app.services.exceptions import SessionStartError
from app.services.runner import _TASKS, SessionRunner
from app.storage.registry import SessionRegistry


async def _drain_background() -> None:
    """Await in-flight streaming tasks so subprocess pipes close in-loop."""
    await asyncio.gather(*list(_TASKS), return_exceptions=True)


def _streaming_claude(tmp_path: Path) -> Path:
    """A fake claude that emits an id, pauses, then finishes."""
    script = tmp_path / "claude.py"
    script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json, sys, time
            def emit(o):
                o["session_id"] = "stream-1"
                sys.stdout.write(json.dumps(o) + "\\n"); sys.stdout.flush()
            emit({"type": "system", "subtype": "init"})
            time.sleep(0.6)
            emit({"type": "result", "subtype": "success", "is_error": False})
            """
        )
    )
    script.chmod(0o755)
    return script


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
async def test_start_without_session_id_raises_start_error(tmp_path) -> None:
    """Ensure a subprocess yielding no session id raises SessionStartError."""
    settings = Settings(
        claude_bin="true",  # exits 0 with no stdout
        workspace_root=str(tmp_path),
        permission_mode="acceptEdits",
    )
    runner = SessionRunner(settings, SessionRegistry())
    with pytest.raises(SessionStartError):
        await runner.start("hi")
    await _drain_background()


@pytest.mark.asyncio
async def test_start_returns_before_subprocess_completes(tmp_path) -> None:
    """Ensure start returns at the first id while streaming continues."""
    settings = Settings(
        claude_bin=str(_streaming_claude(tmp_path)),
        workspace_root=str(tmp_path / "ws"),
        permission_mode="acceptEdits",
    )
    reg = SessionRegistry()
    runner = SessionRunner(settings, reg)

    sid = await runner.start("hi")

    # Returned as soon as the id is known: record exists, still running,
    # and the terminal result event has not landed yet.
    assert sid == "stream-1"
    rec = reg.get(sid)
    assert rec is not None
    assert rec.status == "running"
    assert all(e.type != "result" for e in rec.events)

    # The background task keeps consuming to completion.
    for _ in range(60):
        if reg.get(sid).status == "idle":
            break
        await asyncio.sleep(0.05)
    assert reg.get(sid).status == "idle"
    assert any(e.type == "result" for e in reg.get(sid).events)
    await _drain_background()


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


@pytest.mark.asyncio
async def test_run_blocking_streams_and_awaits(tmp_path) -> None:
    """Ensure run_blocking streams to the registry and returns on completion."""
    settings = Settings(
        claude_bin=str(_streaming_claude(tmp_path)),
        workspace_root=str(tmp_path / "ws"),
        permission_mode="acceptEdits",
    )
    reg = SessionRegistry()
    runner = SessionRunner(settings, reg)
    cwd = str(tmp_path / "step")

    seen: list[str] = []
    sid = await runner.run_blocking(
        "hi", cwd=cwd, permission_mode="plan",
        on_session_id=lambda s: seen.append(s),
    )

    # Returned only after completion: result event present, status idle.
    assert sid == "stream-1"
    assert seen == ["stream-1"]
    rec = reg.get(sid)
    assert rec.status == "idle"
    assert any(e.type == "result" for e in rec.events)
    await _drain_background()


def test_build_argv_permission_mode_override() -> None:
    """Ensure build_argv honours a permission-mode override."""
    settings = Settings(
        claude_bin="claude", workspace_root="/tmp/ws",
        permission_mode="acceptEdits",
    )
    argv = SessionRunner(settings, SessionRegistry()).build_argv(
        "p", permission_mode="plan"
    )
    assert argv[argv.index("--permission-mode") + 1] == "plan"

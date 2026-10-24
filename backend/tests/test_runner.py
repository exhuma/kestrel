"""Tests for the claude runner: argv building, stream consume, one turn."""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import AsyncIterator

import pytest

from app.backends.base import BackendTurnError, TurnRequest
from app.config import Settings
from app.models import EventKind
from app.services.runner import SessionRunner


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


def _oversized_line_claude(tmp_path: Path) -> Path:
    """A fake claude that emits one JSONL line over 64 KiB.

    Reproduces a real event kestrel has hit in production: a single
    stream-json line (e.g. a large tool_result) exceeding asyncio's
    default 64 KiB per-line StreamReader limit.
    """
    script = tmp_path / "claude_big.py"
    script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json, sys
            payload = "x" * 100_000  # comfortably over 64 KiB
            sys.stdout.write(json.dumps({
                "type": "result", "subtype": "success",
                "session_id": "big-1", "is_error": False,
                "result": payload,
            }) + "\\n")
            sys.stdout.flush()
            """
        )
    )
    script.chmod(0o755)
    return script


def _runner() -> SessionRunner:
    settings = Settings(
        claude_bin="claude",
        workspace_root="/tmp/ws",
        permission_mode="edit",
    )
    return SessionRunner(settings)


def test_build_argv_start() -> None:
    """Ensure start argv requests stream-json and permission mode."""
    argv = _runner().build_argv("hello")
    assert argv[:3] == ["claude", "-p", "hello"]
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    assert "--permission-mode" in argv
    assert "--resume" not in argv


def test_build_argv_maps_default_mode_to_claude_flag() -> None:
    """Ensure the neutral default mode becomes Claude's own name."""
    argv = _runner().build_argv("hello")
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"


def test_build_argv_maps_read_only_mode_to_claude_flag() -> None:
    """Ensure the neutral read-only mode becomes Claude's plan mode."""
    argv = _runner().build_argv("hello", permission_mode="read_only")
    assert argv[argv.index("--permission-mode") + 1] == "plan"


def test_build_argv_passes_unknown_mode_through() -> None:
    """Ensure a Claude-native mode in the settings still reaches Claude."""
    argv = _runner().build_argv("hello", permission_mode="bypassPermissions")
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"


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


def _req(cwd: str, **kw: object) -> TurnRequest:
    return TurnRequest(prompt="hi", cwd=cwd, permission_mode="read_only", **kw)


@pytest.mark.asyncio
async def test_consume_returns_session_id_and_result() -> None:
    """Ensure consume reports the session id and the terminal result."""
    seen: list[str] = []
    lines = [
        '{"type":"system","subtype":"init","session_id":"s1"}',
        '{"type":"assistant","message":{}}',
        '{"type":"result","subtype":"success","session_id":"s1",'
        '"result":"done"}',
    ]
    turn = await _runner().consume(
        _lines(lines), _req("/tmp/ws/s1", on_session_id=seen.append)
    )
    assert turn.session_id == "s1"
    assert turn.result is not None
    assert turn.result.text == "done"
    assert seen == ["s1"]


@pytest.mark.asyncio
async def test_consume_resume_reports_the_known_id_up_front() -> None:
    """Ensure a resumed turn announces its session id before any event."""
    seen: list[str] = []
    lines = ['{"type":"assistant","message":{}}']
    turn = await _runner().consume(
        _lines(lines),
        _req("/tmp/ws/s1", resume_id="s1", on_session_id=seen.append),
    )
    assert turn.session_id == "s1"
    assert turn.result is None
    assert seen == ["s1"]


@pytest.mark.asyncio
async def test_run_blocking_without_session_id_raises(tmp_path) -> None:
    """Ensure a subprocess yielding no session id fails the turn."""
    settings = Settings(
        claude_bin="true",  # exits 0 with no stdout
        workspace_root=str(tmp_path),
        permission_mode="edit",
    )
    with pytest.raises(BackendTurnError):
        await SessionRunner(settings).run_blocking(_req(str(tmp_path / "w")))


@pytest.mark.asyncio
async def test_run_blocking_awaits_the_subprocess(tmp_path) -> None:
    """Ensure run_blocking returns only once the run has completed."""
    settings = Settings(
        claude_bin=str(_streaming_claude(tmp_path)),
        workspace_root=str(tmp_path / "ws"),
        permission_mode="edit",
    )
    seen: list[str] = []
    turn = await SessionRunner(settings).run_blocking(
        _req(str(tmp_path / "step"), on_session_id=seen.append)
    )

    assert turn.session_id == "stream-1"
    assert seen == ["stream-1"]
    assert turn.result is not None


@pytest.mark.asyncio
async def test_run_blocking_handles_a_line_over_64kib(tmp_path) -> None:
    """Ensure a single stream-json line over 64 KiB doesn't crash the run.

    Regression test: asyncio's default per-line StreamReader limit is
    64 KiB; a real claude session can legitimately emit a single JSONL
    event (e.g. a tool_result embedding a large file) larger than that.
    """
    settings = Settings(
        claude_bin=str(_oversized_line_claude(tmp_path)),
        workspace_root=str(tmp_path / "ws"),
        permission_mode="edit",
    )
    turn = await SessionRunner(settings).run_blocking(
        _req(str(tmp_path / "step"))
    )

    assert turn.session_id == "big-1"
    assert turn.result is not None
    assert turn.result.kind is EventKind.RESULT
    assert len(turn.result.text) == 100_000


def test_build_argv_permission_mode_override() -> None:
    """Ensure build_argv honours a permission-mode override."""
    settings = Settings(
        claude_bin="claude", workspace_root="/tmp/ws",
        permission_mode="edit",
    )
    argv = SessionRunner(settings).build_argv(
        "p", permission_mode="read_only"
    )
    assert argv[argv.index("--permission-mode") + 1] == "plan"

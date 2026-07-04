"""Tests for the pluggable backend layer (claude-only in this phase)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.backends.base import Capability, TurnRequest
from app.backends.claude_cli import ClaudeCliBackend
from app.backends.registry import BackendRegistry, UnknownBackendError
from app.config import BackendConfig, Settings
from app.storage.registry import SessionRegistry


def _result_claude(tmp_path: Path, payload: str) -> Path:
    """A fake claude that emits an id then a result with ``payload``."""
    script = tmp_path / "claude.py"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import json, sys
            def emit(o):
                o["session_id"] = "turn-1"
                sys.stdout.write(json.dumps(o) + "\\n"); sys.stdout.flush()
            emit({{"type": "system", "subtype": "init"}})
            emit({{"type": "result", "subtype": "success",
                  "is_error": False, "result": {payload!r}}})
            """
        )
    )
    script.chmod(0o755)
    return script


def _settings(**kw: object) -> Settings:
    return Settings(
        claude_bin=kw.pop("claude_bin", "claude"),
        workspace_root=str(kw.pop("workspace_root", "/tmp/ws")),
        permission_mode="acceptEdits",
        **kw,  # type: ignore[arg-type]
    )


def test_claude_backend_advertises_text_and_file_edits() -> None:
    """Ensure the claude backend can serve both text and edit steps."""
    backend = ClaudeCliBackend(_settings(), SessionRegistry(), backend_id="c")
    assert backend.id == "c"
    assert backend.caps == frozenset({Capability.TEXT, Capability.FILE_EDITS})


@pytest.mark.asyncio
async def test_run_turn_returns_the_result_deliverable(tmp_path: Path) -> None:
    """Ensure run_turn awaits completion and returns the RESULT text."""
    settings = _settings(
        claude_bin=str(_result_claude(tmp_path, "the deliverable")),
        workspace_root=str(tmp_path / "ws"),
    )
    reg = SessionRegistry()
    backend = ClaudeCliBackend(settings, reg)

    seen: list[str] = []
    result = await backend.run_turn(
        TurnRequest(prompt="hi", cwd=str(tmp_path / "step"), permission_mode="plan"),
        on_session_id=seen.append,
    )

    assert result.session_id == "turn-1"
    assert result.final_text == "the deliverable"
    assert seen == ["turn-1"]
    assert reg.get("turn-1").status == "idle"


def test_registry_builds_default_claude_backend() -> None:
    """Ensure the default config yields a resolvable claude backend."""
    registry = BackendRegistry(_settings(), SessionRegistry())
    assert isinstance(registry.default_session_backend(), ClaudeCliBackend)
    assert registry.get("claude").id == "claude"


def test_registry_unknown_backend_raises() -> None:
    """Ensure resolving an unconfigured backend id raises."""
    registry = BackendRegistry(_settings(), SessionRegistry())
    with pytest.raises(UnknownBackendError):
        registry.get("nope")


def test_registry_rejects_a_missing_default_at_build() -> None:
    """Ensure a default pointing at no backend fails fast, not on dispatch."""
    settings = _settings(
        backends=[BackendConfig(id="claude", type="claude_cli")],
        default_session_backend="ghost",
    )
    with pytest.raises(UnknownBackendError):
        BackendRegistry(settings, SessionRegistry())

"""Tests for the pluggable backend layer (claude-only in this phase)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.backends.base import Capability, TurnRequest
from app.backends.claude_cli import ClaudeCliBackend
from app.backends.registry import BackendRegistry, UnknownBackendError
from app.config import BackendConfig, Settings
from app.models_board import SpecialistDefinition
from app.policy import SpecialistBackendPolicy, SpecialistCapabilityError


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
    # Pin backends explicitly so the suite never depends on a developer's
    # local backend/.env (which pydantic-settings would otherwise read).
    kw.setdefault(
        "backends", [BackendConfig(id="claude", type="claude_cli")]
    )
    kw.setdefault("default_session_backend", "claude")
    return Settings(
        claude_bin=kw.pop("claude_bin", "claude"),
        workspace_root=str(kw.pop("workspace_root", "/tmp/ws")),
        permission_mode="edit",
        **kw,  # type: ignore[arg-type]
    )


def test_claude_backend_advertises_text_and_file_edits() -> None:
    """Ensure the claude backend can serve both text and edit steps."""
    backend = ClaudeCliBackend(_settings(), backend_id="c")
    assert backend.id == "c"
    assert backend.caps == frozenset({Capability.TEXT, Capability.FILE_EDITS})


@pytest.mark.asyncio
async def test_run_turn_returns_the_result_deliverable(tmp_path: Path) -> None:
    """Ensure run_turn awaits completion and returns the RESULT text."""
    settings = _settings(
        claude_bin=str(_result_claude(tmp_path, "the deliverable")),
        workspace_root=str(tmp_path / "ws"),
    )
    backend = ClaudeCliBackend(settings)

    seen: list[str] = []
    result = await backend.run_turn(
        TurnRequest(
            prompt="hi",
            cwd=str(tmp_path / "step"),
            permission_mode="read_only",
            on_session_id=seen.append,
        )
    )

    assert result.session_id == "turn-1"
    assert result.final_text == "the deliverable"
    assert seen == ["turn-1"]


def test_registry_builds_default_claude_backend() -> None:
    """Ensure the default config yields a resolvable claude backend."""
    registry = BackendRegistry(_settings())
    assert isinstance(registry.default_session_backend(), ClaudeCliBackend)
    assert registry.get("claude").id == "claude"


def test_registry_applies_configured_capability_override() -> None:
    """Ensure a backend can declare a narrower capability set."""
    settings = _settings(
        backends=[
            BackendConfig(
                id="local",
                type="opencode",
                base_url="http://x",
                caps=["text"],
            )
        ],
        default_session_backend="local",
    )
    registry = BackendRegistry(settings)
    assert registry.get("local").caps == frozenset({Capability.TEXT})


def test_registry_unknown_backend_raises() -> None:
    """Ensure resolving an unconfigured backend id raises."""
    registry = BackendRegistry(_settings())
    with pytest.raises(UnknownBackendError):
        registry.get("nope")


def test_registry_unknown_backend_error_lists_configured_ids() -> None:
    """Ensure the error names what IS configured, not just what's missing."""
    registry = BackendRegistry(
        _settings(
            backends=[BackendConfig(id="oc", type="opencode")],
            default_session_backend="oc",
        )
    )
    with pytest.raises(UnknownBackendError, match=r"nope.*\['oc'\]"):
        registry.get("nope")


def test_registry_rejects_a_missing_default_at_build() -> None:
    """Ensure a default pointing at no backend fails fast, not on dispatch."""
    settings = _settings(
        backends=[BackendConfig(id="claude", type="claude_cli")],
        default_session_backend="ghost",
    )
    with pytest.raises(UnknownBackendError, match=r"ghost.*\['claude'\]"):
        BackendRegistry(settings)


# ---- SpecialistBackendPolicy (feature 026: specialist capability routing) --

def _mixed_registry() -> BackendRegistry:
    """A registry with a file-editing agent and a text-only backend."""
    settings = _settings(
        backends=[
            BackendConfig(id="claude", type="claude_cli"),
            BackendConfig(
                id="local", type="opencode", base_url="http://x", caps=["text"]
            ),
        ],
    )
    return BackendRegistry(settings)



def _specialist(**overrides: object) -> SpecialistDefinition:
    """A minimal valid specialist definition, with any field overridden."""
    fields: dict[str, object] = {
        "id": "developer",
        "label": "Engineering",
        "purpose": "Analysis",
        "allowed_card_types": ("analysis",),
        "required_abilities": ("text",),
        "model_policy": "default",
        "workspace_permission": "read_only",
        "prompt": "Ask about approach.",
    }
    fields.update(overrides)
    return SpecialistDefinition(**fields)


def test_specialist_policy_uses_default_backend() -> None:
    """A ``"default"`` model_policy resolves to the default backend."""
    policy = SpecialistBackendPolicy(_mixed_registry(), "claude")
    assert policy.backend_for(_specialist()).id == "claude"


def test_specialist_policy_pinned_backend_wins() -> None:
    """A specialist pinned to a specific backend id resolves to it."""
    policy = SpecialistBackendPolicy(_mixed_registry(), "claude")
    backend = policy.backend_for(_specialist(model_policy="local"))
    assert backend.id == "local"


def test_specialist_policy_rejects_missing_capability() -> None:
    """A text-only backend cannot serve a specialist that needs file edits."""
    policy = SpecialistBackendPolicy(_mixed_registry(), "local")
    with pytest.raises(SpecialistCapabilityError):
        policy.backend_for(
            _specialist(required_abilities=("text", "file_edits"))
        )


def test_specialist_policy_allows_satisfied_capability() -> None:
    """A file-editing backend can serve a specialist that needs file edits."""
    policy = SpecialistBackendPolicy(_mixed_registry(), "claude")
    backend = policy.backend_for(
        _specialist(required_abilities=("text", "file_edits"))
    )
    assert backend.id == "claude"

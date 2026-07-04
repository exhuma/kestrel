"""Tests for the opencode backend (HTTP server mode)."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.backends.base import Capability, TurnRequest
from app.backends.opencode import OpenCodeBackend, _split_model
from app.backends.registry import BackendRegistry
from app.config import BackendConfig, Settings
from app.models import EventKind
from app.storage.registry import SessionRegistry


def _settings() -> Settings:
    return Settings(workspace_root="/tmp/ws", permission_mode="acceptEdits")


def _backend(
    handler, cfg: BackendConfig | None = None
) -> tuple[OpenCodeBackend, SessionRegistry, list[httpx.Request]]:
    registry = SessionRegistry()
    cfg = cfg or BackendConfig(
        id="oc", type="opencode",
        base_url="http://oc.local:4096", model="anthropic/claude-sonnet-4",
    )
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    return OpenCodeBackend(_settings(), registry, cfg, client=client), registry, seen


def _ok_handler(request: httpx.Request) -> httpx.Response:
    """Create a session, then return a text + tool transcript."""
    if request.url.path == "/session":
        return httpx.Response(200, json={"id": "oc-1"})
    if request.url.path == "/session/oc-1/message":
        return httpx.Response(200, json={
            "info": {"id": "msg-1"},
            "parts": [
                {"type": "text", "text": "all done"},
                {"type": "tool", "tool": "read",
                 "state": {"status": "completed",
                           "input": {"path": "x.py"}, "output": "file body"}},
            ],
        })
    return httpx.Response(404)


def test_split_model_parses_provider_and_model() -> None:
    """Ensure provider/model strings become opencode's model object."""
    assert _split_model("anthropic/claude-sonnet-4") == {
        "providerID": "anthropic", "modelID": "claude-sonnet-4",
    }
    assert _split_model("just-a-model") is None
    assert _split_model(None) is None


def test_backend_can_edit_files() -> None:
    """Ensure opencode advertises file editing (a full agent)."""
    backend, _, _ = _backend(_ok_handler)
    assert backend.caps == frozenset({Capability.TEXT, Capability.FILE_EDITS})


@pytest.mark.asyncio
async def test_run_turn_creates_session_and_maps_parts() -> None:
    """Ensure a turn creates a session and maps text + tool parts."""
    backend, reg, seen = _backend(_ok_handler)

    result = await backend.run_turn(
        TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
    )

    assert result.session_id == "oc-1"
    assert result.final_text == "all done"
    rec = reg.get("oc-1")
    assert [e.kind for e in rec.events] == [
        EventKind.USER_TEXT, EventKind.ASSISTANT_TEXT,
        EventKind.TOOL_USE, EventKind.TOOL_RESULT, EventKind.RESULT,
    ]
    tool_use = rec.events[2]
    assert tool_use.tool_name == "read"
    assert tool_use.tool_summary == "x.py"
    assert rec.events[3].text == "file body"
    assert rec.status == "idle"

    # The message request carried the parsed model object.
    msg = next(r for r in seen if r.url.path == "/session/oc-1/message")
    body = json.loads(msg.content)
    assert body["model"] == {"providerID": "anthropic", "modelID": "claude-sonnet-4"}
    assert body["parts"] == [{"type": "text", "text": "do it"}]


@pytest.mark.asyncio
async def test_start_streams_a_turn_in_the_background() -> None:
    """Ensure start returns immediately then completes the turn."""
    backend, reg, _ = _backend(_ok_handler)
    sid = await backend.start("do it")

    for _ in range(100):
        if reg.get(sid) and reg.get(sid).status == "idle":
            break
        await asyncio.sleep(0.01)

    rec = reg.get(sid)
    assert rec.status == "idle"
    assert any(e.kind is EventKind.RESULT for e in rec.events)


@pytest.mark.asyncio
async def test_server_error_surfaces_as_a_failed_result() -> None:
    """Ensure an opencode error never leaves the session stuck running."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/session":
            return httpx.Response(200, json={"id": "oc-1"})
        return httpx.Response(500, json={"error": "boom"})

    backend, reg, _ = _backend(handler)
    sid = await backend.start("do it")

    for _ in range(100):
        if reg.get(sid) and reg.get(sid).status == "idle":
            break
        await asyncio.sleep(0.01)

    rec = reg.get(sid)
    assert rec.status == "idle"
    assert rec.events[-1].kind is EventKind.RESULT
    assert rec.events[-1].is_error is True


def test_registry_builds_an_opencode_backend() -> None:
    """Ensure a configured opencode backend is resolvable."""
    settings = Settings(
        workspace_root="/tmp/ws",
        backends=[
            BackendConfig(
                id="oc", type="opencode", base_url="http://oc:4096"
            )
        ],
        default_session_backend="oc",
    )
    registry = BackendRegistry(settings, SessionRegistry())
    assert isinstance(registry.get("oc"), OpenCodeBackend)

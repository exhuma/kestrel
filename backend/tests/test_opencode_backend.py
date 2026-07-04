"""Tests for the opencode backend (HTTP server mode).

The request/response shapes here mirror a real ``opencode serve`` (1.15.x):
``POST /session`` returns ``{id}``; a turn is sent with the synchronous
``POST /session/:id/message`` and the full transcript (including tool
messages, which the POST response omits) is read from
``GET /session/:id/message``.
"""
from __future__ import annotations

import asyncio
import base64
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
    return Settings(_env_file=None, workspace_root="/tmp/ws")


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


# A transcript with a tool message then a final text message — the shape a
# real turn produces. GET /message is empty until the prompt is POSTed.
_TRANSCRIPT = [
    {"info": {"id": "u1", "role": "user"},
     "parts": [{"type": "text", "text": "do it"}]},
    {"info": {"id": "a1", "role": "assistant"},
     "parts": [{"type": "tool", "tool": "read",
                "state": {"status": "completed",
                          "input": {"path": "x.py"}, "output": "file body"}}]},
    {"info": {"id": "a2", "role": "assistant"},
     "parts": [{"type": "text", "text": "all done"}]},
]


def _transcript_handler():
    state = {"sent": False}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "oc-1"})
        if path == "/session/oc-1/message":
            if request.method == "GET":
                return httpx.Response(
                    200, json=_TRANSCRIPT if state["sent"] else []
                )
            if request.method == "POST":
                state["sent"] = True
                return httpx.Response(
                    200, json={"info": {"id": "a2"},
                               "parts": [{"type": "text", "text": "all done"}]}
                )
        return httpx.Response(404)

    return handler


def test_split_model_parses_provider_and_model() -> None:
    """Ensure provider/model strings become opencode's model object."""
    assert _split_model("anthropic/claude-sonnet-4") == {
        "providerID": "anthropic", "modelID": "claude-sonnet-4",
    }
    assert _split_model("just-a-model") is None
    assert _split_model(None) is None


def test_backend_can_edit_files() -> None:
    """Ensure opencode advertises file editing (a full agent)."""
    backend, _, _ = _backend(_transcript_handler())
    assert backend.caps == frozenset({Capability.TEXT, Capability.FILE_EDITS})


@pytest.mark.asyncio
async def test_run_turn_maps_tool_and_text_messages() -> None:
    """Ensure a turn maps the tool message and the final text message."""
    backend, reg, seen = _backend(_transcript_handler())

    result = await backend.run_turn(
        TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
    )

    assert result.session_id == "oc-1"
    assert result.final_text == "all done"
    rec = reg.get("oc-1")
    assert [e.kind for e in rec.events] == [
        EventKind.USER_TEXT, EventKind.TOOL_USE,
        EventKind.TOOL_RESULT, EventKind.ASSISTANT_TEXT, EventKind.RESULT,
    ]
    assert rec.events[1].tool_name == "read"
    assert rec.events[1].tool_summary == "x.py"
    assert rec.events[2].text == "file body"
    assert rec.status == "idle"

    post = next(
        r for r in seen
        if r.url.path == "/session/oc-1/message" and r.method == "POST"
    )
    body = json.loads(post.content)
    assert body["model"] == {"providerID": "anthropic", "modelID": "claude-sonnet-4"}
    assert body["parts"] == [{"type": "text", "text": "do it"}]


@pytest.mark.asyncio
async def test_start_streams_a_turn_in_the_background() -> None:
    """Ensure start returns immediately then completes the turn."""
    backend, reg, _ = _backend(_transcript_handler())
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
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "oc-1"})
        if request.method == "GET":
            return httpx.Response(200, json=[])
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


@pytest.mark.asyncio
async def test_basic_auth_sent_when_password_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure a configured password produces HTTP Basic auth on every call."""
    monkeypatch.setenv("OC_PW", "s3cret")
    cfg = BackendConfig(
        id="oc", type="opencode",
        base_url="http://oc.local:4096", model="anthropic/claude-sonnet-4",
        api_key_env="OC_PW",
    )
    backend, _, seen = _backend(_transcript_handler(), cfg)

    await backend.run_turn(
        TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
    )

    expected = "Basic " + base64.b64encode(b"opencode:s3cret").decode()
    assert seen  # requests were made
    assert all(r.headers.get("authorization") == expected for r in seen)


@pytest.mark.asyncio
async def test_custom_basic_auth_username() -> None:
    """Ensure the username override is honoured."""
    import os

    os.environ["OC_PW2"] = "pw"
    try:
        cfg = BackendConfig(
            id="oc", type="opencode", base_url="http://oc.local:4096",
            api_key_env="OC_PW2", username="admin",
        )
        backend, _, seen = _backend(_transcript_handler(), cfg)
        await backend.run_turn(
            TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
        )
    finally:
        os.environ.pop("OC_PW2", None)

    expected = "Basic " + base64.b64encode(b"admin:pw").decode()
    assert all(r.headers.get("authorization") == expected for r in seen)


@pytest.mark.asyncio
async def test_no_auth_header_without_a_password() -> None:
    """Ensure no auth is sent to an unsecured server."""
    backend, _, seen = _backend(_transcript_handler())
    await backend.run_turn(
        TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
    )
    assert all(r.headers.get("authorization") is None for r in seen)


def test_registry_builds_an_opencode_backend() -> None:
    """Ensure a configured opencode backend is resolvable."""
    settings = Settings(
        _env_file=None, workspace_root="/tmp/ws",
        backends=[
            BackendConfig(id="oc", type="opencode", base_url="http://oc:4096")
        ],
        default_session_backend="oc",
    )
    registry = BackendRegistry(settings, SessionRegistry())
    assert isinstance(registry.get("oc"), OpenCodeBackend)

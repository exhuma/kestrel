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
import os

import httpx
import pytest

from app.backends.base import Capability, TurnRequest
from app.backends.opencode import OpenCodeBackend, _split_model
from app.backends.registry import BackendRegistry
from app.config import BackendConfig, Settings
from app.models import EventKind
from app.storage.registry import SessionRegistry


def _settings(ws: str = "/tmp/ws") -> Settings:
    return Settings(_env_file=None, workspace_root=ws)


def _backend(
    handler, cfg: BackendConfig | None = None, ws: str = "/tmp/ws"
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
    backend = OpenCodeBackend(_settings(ws), registry, cfg, client=client)
    return backend, registry, seen


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


def _sse(*events: dict) -> bytes:
    """Encode events as an opencode /event SSE body (data: <json>\\n\\n)."""
    frames = [f"data: {json.dumps(e)}\n\n" for e in events]
    return "".join(frames).encode("utf-8")


def _permission_event(session_id: str, tool: str, request_id: str) -> dict:
    """A permission.asked frame as opencode's /event bus emits it."""
    return {
        "type": "permission.asked",
        "properties": {
            "id": request_id,
            "sessionID": session_id,
            "permission": tool,
            "patterns": [],
            "metadata": {},
            "always": [],
        },
    }


def _reply_for(seen: list[httpx.Request]) -> dict:
    """Return the JSON body of the single /permission reply that was sent."""
    replies = [
        r for r in seen if "/permission/" in r.url.path and r.method == "POST"
    ]
    assert len(replies) == 1, f"expected one reply, got {len(replies)}"
    return json.loads(replies[0].content)


@pytest.mark.asyncio
async def test_read_only_turn_disables_file_mutating_tools() -> None:
    """Ensure a read-only (plan) turn tells opencode to disable edit tools."""
    backend, _, seen = _backend(_transcript_handler())
    await backend.run_turn(
        TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="plan")
    )
    post = next(
        r
        for r in seen
        if r.url.path == "/session/oc-1/message" and r.method == "POST"
    )
    tools = json.loads(post.content)["tools"]
    assert tools == {"edit": False, "write": False, "patch": False}


@pytest.mark.asyncio
async def test_edit_turn_does_not_restrict_tools() -> None:
    """Ensure an edit-capable turn leaves all tools enabled."""
    backend, _, seen = _backend(_transcript_handler())
    await backend.run_turn(
        TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="acceptEdits")
    )
    post = next(
        r
        for r in seen
        if r.url.path == "/session/oc-1/message" and r.method == "POST"
    )
    assert "tools" not in json.loads(post.content)


@pytest.mark.asyncio
async def test_permission_loop_approves_a_read() -> None:
    """Ensure a read permission is auto-approved so headless never blocks."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/event":
            return httpx.Response(
                200, content=_sse(_permission_event("s1", "read", "per_1"))
            )
        return httpx.Response(200, json=True)

    backend, _, seen = _backend(handler)
    await backend._permission_loop("s1", "/tmp/s", read_only=True)
    assert _reply_for(seen) == {"reply": "once"}


@pytest.mark.asyncio
async def test_permission_loop_rejects_edit_on_read_only_turn() -> None:
    """Ensure a file-edit permission is rejected during a read-only turn."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/event":
            return httpx.Response(
                200, content=_sse(_permission_event("s1", "edit", "per_9"))
            )
        return httpx.Response(200, json=True)

    backend, _, seen = _backend(handler)
    await backend._permission_loop("s1", "/tmp/s", read_only=True)
    assert _reply_for(seen) == {"reply": "reject"}
    assert seen[-1].url.path == "/permission/per_9/reply"


@pytest.mark.asyncio
async def test_permission_loop_allows_edit_when_editable() -> None:
    """Ensure edits are approved on an edit-capable (implement) turn."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/event":
            return httpx.Response(
                200, content=_sse(_permission_event("s1", "edit", "per_2"))
            )
        return httpx.Response(200, json=True)

    backend, _, seen = _backend(handler)
    await backend._permission_loop("s1", "/tmp/s", read_only=False)
    assert _reply_for(seen) == {"reply": "once"}


@pytest.mark.asyncio
async def test_permission_loop_ignores_other_sessions() -> None:
    """Ensure prompts for a different session are not answered."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/event":
            return httpx.Response(
                200, content=_sse(_permission_event("other", "read", "per_3"))
            )
        return httpx.Response(200, json=True)

    backend, _, seen = _backend(handler)
    await backend._permission_loop("s1", "/tmp/s", read_only=True)
    assert not [r for r in seen if "/permission/" in r.url.path]


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
    assert body["model"] == {
        "providerID": "anthropic",
        "modelID": "claude-sonnet-4",
    }
    assert body["parts"] == [{"type": "text", "text": "do it"}]


@pytest.mark.asyncio
async def test_run_turn_scopes_requests_to_the_working_directory() -> None:
    """Ensure opencode requests carry the checked-out repo as the directory.

    Without a directory, opencode falls back to the ``opencode serve``
    process's own cwd and edits the wrong folder (resolution order:
    ``?directory=`` query > ``x-opencode-directory`` header > process.cwd()).
    """
    backend, _, seen = _backend(_transcript_handler())

    await backend.run_turn(
        TurnRequest(
            prompt="do it", cwd="/repo/checkout", permission_mode="n/a"
        )
    )

    assert seen  # requests were made
    assert all(
        r.url.params.get("directory") == "/repo/checkout" for r in seen
    )


@pytest.mark.asyncio
async def test_relative_cwd_is_sent_as_an_absolute_directory() -> None:
    """Ensure a relative working dir is resolved before opencode sees it.

    opencode runs as a separate process with its own cwd (the default
    workspace root is relative, ``./.kestrel-workspaces``), so a relative
    ``directory`` would resolve against the wrong base. kestrel must send an
    absolute path.
    """
    backend, _, seen = _backend(_transcript_handler())

    await backend.run_turn(
        TurnRequest(
            prompt="do it",
            cwd="./.kestrel-workspaces/session-abc",
            permission_mode="n/a",
        )
    )

    expected = os.path.abspath("./.kestrel-workspaces/session-abc")
    assert expected.startswith("/")  # absolute
    assert seen
    assert all(r.url.params.get("directory") == expected for r in seen)


@pytest.mark.asyncio
async def test_start_streams_a_turn_in_the_background(tmp_path) -> None:
    """Ensure start returns immediately then completes the turn."""
    backend, reg, _ = _backend(_transcript_handler(), ws=str(tmp_path))
    sid = await backend.start("do it")

    for _ in range(100):
        if reg.get(sid) and reg.get(sid).status == "idle":
            break
        await asyncio.sleep(0.01)

    rec = reg.get(sid)
    assert rec.status == "idle"
    assert any(e.kind is EventKind.RESULT for e in rec.events)


@pytest.mark.asyncio
async def test_server_error_surfaces_as_a_failed_result(tmp_path) -> None:
    """Ensure an opencode error never leaves the session stuck running."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": "oc-1"})
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(500, json={"error": "boom"})

    backend, reg, _ = _backend(handler, ws=str(tmp_path))
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
async def test_inline_password_produces_basic_auth() -> None:
    """Ensure a password given inline (no env var) is sent as Basic auth."""
    cfg = BackendConfig(
        id="oc", type="opencode", base_url="http://oc.local:4096",
        password="changeme",
    )
    backend, _, seen = _backend(_transcript_handler(), cfg)
    await backend.run_turn(
        TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
    )
    expected = "Basic " + base64.b64encode(b"opencode:changeme").decode()
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

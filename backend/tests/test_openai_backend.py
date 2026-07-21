"""Tests for the OpenAI-compatible (self-hosted LLM) backend."""
from __future__ import annotations

import asyncio
import json
from typing import Callable

import httpx
import pytest

from app.backends.base import Capability, TurnRequest
from app.backends.openai_compat import OpenAICompatBackend
from app.backends.registry import BackendRegistry
from app.config import BackendConfig, Settings
from app.models import EventKind
from app.storage.registry import SessionRegistry


def _settings() -> Settings:
    return Settings(workspace_root="/tmp/ws", permission_mode="acceptEdits")


def _backend(
    handler: Callable[[httpx.Request], httpx.Response],
    cfg: BackendConfig | None = None,
) -> tuple[OpenAICompatBackend, SessionRegistry]:
    registry = SessionRegistry()
    cfg = cfg or BackendConfig(
        id="local", type="openai_compat",
        base_url="http://model.local/v1", model="llama3",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    backend = OpenAICompatBackend(_settings(), registry, cfg, client=client)
    return backend, registry


def _echo(captured: list[dict]) -> Callable[[httpx.Request], httpx.Response]:
    """A handler that records each request and replies "reply-<n msgs>"."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        n = len(body["messages"])
        return httpx.Response(
            200, json={"choices": [{"message": {"content": f"reply-{n}"}}]}
        )
    return handler


def _sse(*chunks: dict) -> bytes:
    """Build an OpenAI-style SSE completion body from delta chunks."""
    lines = ["data: " + json.dumps(c) for c in chunks]
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def _stream(*chunks: dict) -> Callable[[httpx.Request], httpx.Response]:
    """A handler that returns the chunks as a streaming SSE response."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(*chunks),
        )
    return handler


def _delta(**delta: object) -> dict:
    return {"choices": [{"delta": delta}]}


def test_backend_is_text_only() -> None:
    """Ensure the LLM backend cannot serve file-editing steps."""
    backend, _ = _backend(_echo([]))
    assert backend.caps == frozenset({Capability.TEXT})


@pytest.mark.asyncio
async def test_run_turn_emits_canonical_events_and_calls_endpoint() -> None:
    """Ensure a turn records user/assistant/result and posts the prompt."""
    captured: list[dict] = []
    backend, reg = _backend(_echo(captured))

    result = await backend.run_turn(
        TurnRequest(prompt="hello", cwd="/tmp/s", permission_mode="n/a")
    )

    rec = reg.get(result.session_id)
    assert [e.kind for e in rec.events] == [
        EventKind.USER_TEXT, EventKind.ASSISTANT_TEXT, EventKind.RESULT,
    ]
    assert result.final_text == "reply-1"
    assert rec.events[1].text == "reply-1"
    assert rec.events[1].model == "llama3"
    assert rec.status == "idle"
    assert captured[0]["model"] == "llama3"
    assert captured[0]["messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_resume_replays_prior_turns_as_history() -> None:
    """Ensure a resumed turn resends the whole conversation (stateless)."""
    captured: list[dict] = []
    backend, reg = _backend(_echo(captured))

    first = await backend.run_turn(
        TurnRequest(prompt="hi", cwd="/tmp/s", permission_mode="n/a")
    )
    second = await backend.run_turn(
        TurnRequest(
            prompt="again", cwd="/tmp/s", permission_mode="n/a",
            resume_id=first.session_id,
        )
    )

    # Second call carries: user hi, assistant reply-1, user again.
    assert len(captured[1]["messages"]) == 3
    assert captured[1]["messages"][-1] == {"role": "user", "content": "again"}
    assert second.final_text == "reply-3"


@pytest.mark.asyncio
async def test_start_streams_a_turn_in_the_background() -> None:
    """Ensure start returns immediately then completes the turn."""
    backend, reg = _backend(_echo([]))
    sid = await backend.start("hello")

    for _ in range(100):
        if reg.get(sid).status == "idle":
            break
        await asyncio.sleep(0.01)

    rec = reg.get(sid)
    assert rec.status == "idle"
    assert any(e.kind is EventKind.RESULT for e in rec.events)


@pytest.mark.asyncio
async def test_endpoint_failure_surfaces_as_a_failed_result() -> None:
    """Ensure an endpoint error never leaves the session stuck running."""
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "model offline"})

    backend, reg = _backend(boom)
    sid = await backend.start("hi")

    for _ in range(100):
        if reg.get(sid).status == "idle":
            break
        await asyncio.sleep(0.01)

    rec = reg.get(sid)
    assert rec.status == "idle"
    last = rec.events[-1]
    assert last.kind is EventKind.RESULT
    assert last.is_error is True


@pytest.mark.asyncio
async def test_streaming_emits_thinking_generating_and_final_text() -> None:
    """Ensure a reasoning stream surfaces thinking + generating phases."""
    backend, reg = _backend(_stream(
        _delta(reasoning="let me think"),
        _delta(content="Hel"),
        _delta(content="lo"),
    ))
    result = await backend.run_turn(
        TurnRequest(prompt="hi", cwd="/tmp/s", permission_mode="n/a")
    )
    rec = reg.get(result.session_id)
    kinds = [e.kind for e in rec.events]
    assert kinds == [
        EventKind.USER_TEXT,
        EventKind.THINKING,            # reasoning phase (live)
        EventKind.SYSTEM,              # "generating" marker (live)
        EventKind.ASSISTANT_TEXT,      # authoritative full reply
        EventKind.RESULT,
    ]
    assert rec.events[2].subtype == "generating"
    assert result.final_text == "Hello"
    assert rec.events[3].text == "Hello"  # history-bearing event is complete


@pytest.mark.asyncio
async def test_streaming_without_reasoning_still_works() -> None:
    """Ensure a model that emits no reasoning yields no THINKING, no error."""
    backend, reg = _backend(_stream(
        _delta(content="just "),
        _delta(content="text"),
    ))
    result = await backend.run_turn(
        TurnRequest(prompt="hi", cwd="/tmp/s", permission_mode="n/a")
    )
    rec = reg.get(result.session_id)
    kinds = [e.kind for e in rec.events]
    assert EventKind.THINKING not in kinds
    assert EventKind.SYSTEM in kinds  # generating marker present
    assert result.final_text == "just text"


@pytest.mark.asyncio
async def test_streaming_surfaces_tool_calls() -> None:
    """Ensure a streamed tool call becomes a TOOL_USE activity event."""
    backend, reg = _backend(_stream(
        _delta(tool_calls=[{"index": 0, "function": {"name": "web_search"}}]),
        _delta(content="done"),
    ))
    result = await backend.run_turn(
        TurnRequest(prompt="hi", cwd="/tmp/s", permission_mode="n/a")
    )
    rec = reg.get(result.session_id)
    tool_events = [e for e in rec.events if e.kind is EventKind.TOOL_USE]
    assert [e.tool_name for e in tool_events] == ["web_search"]
    assert result.final_text == "done"


def test_registry_builds_an_openai_backend() -> None:
    """Ensure a configured openai_compat backend is resolvable."""
    settings = Settings(
        workspace_root="/tmp/ws",
        backends=[
            BackendConfig(
                id="local", type="openai_compat", base_url="http://x/v1"
            )
        ],
        default_session_backend="local",
    )
    registry = BackendRegistry(settings, SessionRegistry())
    assert isinstance(registry.get("local"), OpenAICompatBackend)

"""Losing the opencode server mid-turn is reported as an outage (#33).

The sidecar can die at any time (an OOM kill, a restart). That is one
event with one clear log line, and it must not be mistaken for a failure
of whatever was using the connection at the time.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app.backends import opencode_permissions
from app.backends.base import BackendUnavailable, TurnRequest
from app.backends.opencode_permissions import run_permission_loop
from tests.test_opencode_backend import (
    _TRANSCRIPT,
    _backend,
    _permission_event,
    _sse,
)

_DIRECTORY = "/tmp/s"
#: The stream that dropped, and the one that replaced it.
_STREAMS_OPENED = 2


@pytest.fixture(autouse=True)
def _reconnect_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opencode_permissions, "RECONNECT_SECONDS", 0)


def _turn_request() -> TurnRequest:
    return TurnRequest(prompt="do it", cwd=_DIRECTORY, permission_mode="edit")


def _turn_handler(*, on_event=None, on_prompt=None, on_dispose=None):
    """A server running one turn; each hook replaces one route."""
    state = {"sent": False}

    def prompt(_request: httpx.Request) -> httpx.Response:
        state["sent"] = True
        return httpx.Response(200, json={"info": {"id": "a2"}})

    def transcript(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_TRANSCRIPT if state["sent"] else [])

    routes = {
        ("GET", "/event"): on_event,
        ("POST", "/instance/dispose"): on_dispose,
        ("POST", "/session"): lambda _request: httpx.Response(
            200, json={"id": "oc-1"}
        ),
        ("POST", "/session/oc-1/message"): on_prompt or prompt,
        ("GET", "/session/oc-1/message"): transcript,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        route = routes.get((request.method, request.url.path))
        return route(request) if route else httpx.Response(200, json=True)

    return handler


@pytest.mark.asyncio
async def test_a_dropped_event_stream_reconnects() -> None:
    """Ensure prompts asked after a dropped stream are still answered."""
    streams = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/event":
            streams.append(request)
            if len(streams) == 1:
                raise httpx.RemoteProtocolError("peer closed", request=request)
            return httpx.Response(
                200, content=_sse(_permission_event("oc-1", "bash", "per_1"))
            )
        return httpx.Response(200, json=True)

    backend, seen = _backend(handler)

    await run_permission_loop(
        backend._conn, "oc-1", _DIRECTORY, read_only=False
    )

    assert len(streams) == _STREAMS_OPENED
    assert any("/permissions/per_1" in r.url.path for r in seen)


@pytest.mark.asyncio
async def test_a_dropped_event_stream_is_logged_without_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure a reconnect is one plain line naming the session."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadError("reset", request=request)
        return httpx.Response(200, content=b"")

    backend, _ = _backend(handler)

    with caplog.at_level(logging.DEBUG, logger=opencode_permissions.__name__):
        await run_permission_loop(
            backend._conn, "oc-1", _DIRECTORY, read_only=False
        )

    (warning,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "oc-1" in warning.getMessage()
    assert warning.exc_info is None


@pytest.mark.asyncio
async def test_a_broken_event_stream_does_not_fail_a_finished_turn() -> None:
    """Ensure the turn's own result stands when only the stream failed."""

    def on_event(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("reset", request=request)

    backend, _ = _backend(_turn_handler(on_event=on_event))

    result = await backend.run_turn(_turn_request())

    assert result.final_text == "all done"


@pytest.mark.asyncio
async def test_a_lost_connection_is_one_clear_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure losing the server raises an outage, without stack traces."""

    def on_prompt(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError(
            "Server disconnected without sending a response.", request=request
        )

    def on_event(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("peer closed", request=request)

    backend, _ = _backend(_turn_handler(on_event=on_event, on_prompt=on_prompt))

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(BackendUnavailable, match="opencode"),
    ):
        await backend.run_turn(_turn_request())

    assert not [r for r in caplog.records if r.exc_info]
    (aborted,) = [
        r for r in caplog.records
        if r.name == "kestrel.agent" and r.levelno == logging.WARNING
    ]
    assert "BackendUnavailable" not in aborted.getMessage()
    assert "connection to opencode lost" in aborted.getMessage()


@pytest.mark.asyncio
async def test_a_slow_answer_is_not_an_outage() -> None:
    """Ensure a read timeout stays what it is: the model being slow."""

    def on_prompt(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    backend, _ = _backend(_turn_handler(on_prompt=on_prompt))

    with pytest.raises(httpx.ReadTimeout):
        await backend.run_turn(_turn_request())


@pytest.mark.asyncio
async def test_a_finished_turn_releases_its_directory() -> None:
    """Ensure opencode is told to free what it holds for the directory."""
    disposed = []

    def on_dispose(request: httpx.Request) -> httpx.Response:
        disposed.append(request.url.params["directory"])
        return httpx.Response(200, json=True)

    backend, _ = _backend(_turn_handler(on_dispose=on_dispose))

    await backend.run_turn(_turn_request())

    assert disposed == [_DIRECTORY]


@pytest.mark.asyncio
async def test_a_failed_release_does_not_fail_the_turn() -> None:
    """Ensure a server without the endpoint costs nothing but the release."""

    def on_dispose(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    backend, _ = _backend(_turn_handler(on_dispose=on_dispose))

    result = await backend.run_turn(_turn_request())

    assert result.final_text == "all done"


@pytest.mark.asyncio
async def test_a_directory_in_use_is_not_released() -> None:
    """Ensure one turn ending leaves another in the directory running."""
    disposed = []

    def on_dispose(request: httpx.Request) -> httpx.Response:
        disposed.append(request.url.params["directory"])
        return httpx.Response(200, json=True)

    backend, _ = _backend(_turn_handler(on_dispose=on_dispose))

    async with backend._directories.turn(_DIRECTORY):
        await backend.run_turn(_turn_request())
        assert disposed == []

    assert disposed == [_DIRECTORY]

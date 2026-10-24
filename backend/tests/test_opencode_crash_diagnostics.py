"""Tests for opencode's run_turn crash diagnostics.

A mid-turn crash (e.g. the server disconnecting) must leave a
diagnosable trail: a logged traceback naming the session id when one is
known. See ``run_turn`` in ``app.backends.opencode``.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app.backends.base import TurnRequest
from app.backends.opencode import OpenCodeBackend
from app.config import BackendConfig, Settings


def _backend(handler) -> OpenCodeBackend:
    cfg = BackendConfig(
        id="oc", type="opencode",
        base_url="http://oc.local:4096", model="anthropic/claude-sonnet-4",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(_env_file=None, workspace_root="/tmp/ws")
    return OpenCodeBackend(settings, cfg, client=client)


def _turn_failure_handler(create_ok: bool = True):
    """A handler where ``/session`` succeeds (or not) but message posting
    500s — simulates a mid-turn crash such as a dropped connection."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/session" and request.method == "POST":
            if create_ok:
                return httpx.Response(200, json={"id": "oc-1"})
            return httpx.Response(500, json={"error": "boom"})
        if request.url.path == "/session/oc-1/message":
            if request.method == "GET":
                return httpx.Response(200, json=[])
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(404)

    return handler


@pytest.mark.asyncio
async def test_run_turn_logs_the_session_id_on_resume_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A crash mid-turn on a resumed session is logged with its id."""
    backend = _backend(_turn_failure_handler())

    with caplog.at_level(logging.WARNING, logger="app.backends.opencode"), (
        pytest.raises(httpx.HTTPStatusError)
    ):
        await backend.run_turn(
            TurnRequest(
                prompt="do it", cwd="/tmp/s", permission_mode="n/a",
                resume_id="oc-1",
            )
        )

    assert "run_turn failed (session=oc-1" in caplog.text


@pytest.mark.asyncio
async def test_run_turn_logs_the_session_id_after_fresh_create(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A crash mid-turn on a freshly created session is still diagnosable."""
    backend = _backend(_turn_failure_handler())

    with caplog.at_level(logging.WARNING, logger="app.backends.opencode"), (
        pytest.raises(httpx.HTTPStatusError)
    ):
        await backend.run_turn(
            TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
        )

    assert "run_turn failed (session=oc-1" in caplog.text


@pytest.mark.asyncio
async def test_run_turn_logs_and_reraises_when_create_session_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A crash before any session id exists still leaves the exception log."""
    backend = _backend(_turn_failure_handler(create_ok=False))

    with caplog.at_level(logging.WARNING, logger="app.backends.opencode"), (
        pytest.raises(httpx.HTTPStatusError)
    ):
        await backend.run_turn(
            TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
        )

    assert "run_turn failed" in caplog.text
    assert "opencode request failed" in caplog.text


@pytest.mark.asyncio
async def test_create_session_logs_when_no_session_id_returned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A malformed create-session response (no id) is logged, not silent."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/session" and request.method == "POST":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    backend = _backend(handler)

    with caplog.at_level(logging.WARNING, logger="app.backends.opencode"), (
        pytest.raises(RuntimeError, match="did not return a session id")
    ):
        await backend.run_turn(
            TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
        )

    assert "no session id" in caplog.text

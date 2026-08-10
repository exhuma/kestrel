"""Tests for opencode's run_turn crash diagnostics.

A mid-turn crash (e.g. the server disconnecting) must leave a
diagnosable trail: a session-level error event when a session id is
known, and a logged traceback either way. See ``run_turn`` and
``_record_turn_error`` in ``app.backends.opencode``.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app.backends.base import TurnRequest
from app.backends.opencode import OpenCodeBackend
from app.config import BackendConfig, Settings
from app.models import EventKind
from app.storage.registry import SessionRegistry


def _backend(handler) -> tuple[OpenCodeBackend, SessionRegistry]:
    registry = SessionRegistry()
    cfg = BackendConfig(
        id="oc", type="opencode",
        base_url="http://oc.local:4096", model="anthropic/claude-sonnet-4",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(_env_file=None, workspace_root="/tmp/ws")
    backend = OpenCodeBackend(settings, registry, cfg, client=client)
    return backend, registry


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
async def test_run_turn_records_session_error_on_resume_failure() -> None:
    """A crash mid-turn on a resumed session leaves a diagnosable record."""
    backend, reg = _backend(_turn_failure_handler())

    with pytest.raises(httpx.HTTPStatusError):
        await backend.run_turn(
            TurnRequest(
                prompt="do it", cwd="/tmp/s", permission_mode="n/a",
                resume_id="oc-1",
            )
        )

    rec = reg.get("oc-1")
    assert rec is not None
    assert rec.events[-1].kind is EventKind.RESULT
    assert rec.events[-1].is_error is True
    assert "500" in (rec.events[-1].text or "")


@pytest.mark.asyncio
async def test_run_turn_records_session_error_after_fresh_create() -> None:
    """A crash mid-turn on a freshly created session is still diagnosable."""
    backend, reg = _backend(_turn_failure_handler())

    with pytest.raises(httpx.HTTPStatusError):
        await backend.run_turn(
            TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
        )

    rec = reg.get("oc-1")
    assert rec is not None
    assert rec.events[-1].kind is EventKind.RESULT
    assert rec.events[-1].is_error is True


@pytest.mark.asyncio
async def test_run_turn_logs_and_reraises_when_create_session_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A crash before any session id exists has nothing to record onto —
    the exception log is the only diagnostic trail in that case."""
    backend, reg = _backend(_turn_failure_handler(create_ok=False))

    with caplog.at_level(logging.WARNING, logger="app.backends.opencode"), (
        pytest.raises(httpx.HTTPStatusError)
    ):
        await backend.run_turn(
            TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
        )

    assert not reg.list()
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

    backend, _ = _backend(handler)

    with caplog.at_level(logging.WARNING, logger="app.backends.opencode"), (
        pytest.raises(RuntimeError, match="did not return a session id")
    ):
        await backend.run_turn(
            TurnRequest(prompt="do it", cwd="/tmp/s", permission_mode="n/a")
        )

    assert "no session id" in caplog.text

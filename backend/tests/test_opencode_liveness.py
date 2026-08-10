"""Tests for opencode's check_alive liveness probe."""
from __future__ import annotations

import httpx
import pytest

from app.backends.opencode import OpenCodeBackend
from app.config import BackendConfig, Settings
from app.storage.registry import SessionRegistry


def _backend(handler) -> OpenCodeBackend:
    registry = SessionRegistry()
    cfg = BackendConfig(
        id="oc", type="opencode", base_url="http://oc.local:4096",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(_env_file=None, workspace_root="/tmp/ws")
    return OpenCodeBackend(settings, registry, cfg, client=client)


@pytest.mark.asyncio
async def test_check_alive_true_when_session_is_listed() -> None:
    """Ensure a session present in GET /session reports alive."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "oc-1"}, {"id": "oc-2"}])

    result = await _backend(handler).check_alive("oc-1")
    assert result.alive is True
    assert result.reason is None


@pytest.mark.asyncio
async def test_check_alive_false_when_session_is_missing() -> None:
    """Ensure a session absent from the list reports dead with a reason."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "oc-2"}])

    result = await _backend(handler).check_alive("oc-1")
    assert result.alive is False
    assert result.reason == "opencode session no longer exists — likely crashed"


@pytest.mark.asyncio
async def test_check_alive_false_when_opencode_is_unreachable() -> None:
    """Ensure a transport failure reports dead rather than raising."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    result = await _backend(handler).check_alive("oc-1")
    assert result.alive is False
    assert "could not reach opencode" in (result.reason or "")

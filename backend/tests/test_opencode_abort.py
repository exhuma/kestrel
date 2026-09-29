"""A cancelled opencode turn aborts its session (#66)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.backends.base import TurnRequest
from app.backends.opencode import OpenCodeBackend
from app.config import BackendConfig
from app.storage.registry import SessionRegistry
from tests.test_opencode_backend import _settings


def _hanging_server(seen: list[str]) -> httpx.AsyncClient:
    """An opencode server whose model never finishes answering."""

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        path = request.url.path
        if request.method == "POST" and path == "/session":
            return httpx.Response(200, json={"id": "s1"})
        if request.method == "POST" and path == "/session/s1/message":
            await asyncio.sleep(10)
        if path == "/session/s1/message":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=True)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_a_timed_out_turn_aborts_its_session() -> None:
    """Ensure opencode stops working a turn kestrel gave up on, instead
    of calling the model on its own, unseen."""
    seen: list[str] = []
    backend = OpenCodeBackend(
        _settings(), SessionRegistry(),
        BackendConfig(id="oc", type="opencode", base_url="http://oc.local"),
        client=_hanging_server(seen),
    )

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            backend.run_turn(TurnRequest(
                prompt="classify", cwd="", permission_mode="plan"
            )),
            timeout=0.2,
        )
    for _ in range(50):
        if "POST /session/s1/abort" in seen:
            break
        await asyncio.sleep(0.01)

    assert "POST /session/s1/abort" in seen

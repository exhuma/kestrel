"""Tests for OpenCode workflow permission restrictions."""
from __future__ import annotations

import json

import httpx
import pytest

from app.backends.opencode_permissions import (
    OpenCodeConnection,
    run_permission_loop,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["question", "task"])
async def test_read_only_turn_rejects_blocking_tools(tool: str) -> None:
    """Ensure a read-only turn cannot wait for input or delegate work."""
    replies: list[dict[str, object]] = []

    async def request(*_args, **_kwargs) -> object:
        """Record the permission response without making a network call."""
        replies.append(_kwargs["json"])
        return True

    def handler(_request: httpx.Request) -> httpx.Response:
        """Return one delegation permission request on the event stream."""
        event = {
            "type": "permission.asked",
            "properties": {
                "id": "per_3",
                "sessionID": "s1",
                "permission": tool,
                "patterns": [],
                "metadata": {},
                "always": [],
            },
        }
        return httpx.Response(200, content=f"data: {json.dumps(event)}\n\n")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connection = OpenCodeConnection(
        base_url="http://oc.local",
        auth=None,
        client=client,
        request=request,
    )
    await run_permission_loop(connection, "s1", "/tmp/s", read_only=True)
    assert replies == [{"response": "reject"}]

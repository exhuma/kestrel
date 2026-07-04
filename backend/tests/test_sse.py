"""Tests for the SSE transport encoder."""
from __future__ import annotations

import asyncio
import json

import pytest

from app import sse
from app.sse import KEEPALIVE, encode, with_heartbeat


def test_encode_wraps_payload_in_sse_frame() -> None:
    """Ensure encode produces a `data: <json>\\n\\n` frame."""
    frame = encode({"type": "system", "session_id": "s1", "raw": {}})
    text = frame.decode("utf-8")
    assert text.startswith("data: ")
    assert text.endswith("\n\n")
    payload = json.loads(text[len("data: ") :].strip())
    assert payload == {"type": "system", "session_id": "s1", "raw": {}}


def test_keepalive_is_an_ignored_sse_comment() -> None:
    """Ensure the keepalive frame is a comment (starts with a colon)."""
    assert KEEPALIVE.decode("utf-8") == ": keepalive\n\n"


@pytest.mark.asyncio
async def test_with_heartbeat_yields_items_then_keepalive_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure queued items pass through and idle time yields a None tick."""
    monkeypatch.setattr(sse, "HEARTBEAT_SECONDS", 0.02)
    q: asyncio.Queue[str] = asyncio.Queue()
    q.put_nowait("a")

    gen = with_heartbeat(q)
    assert await gen.__anext__() == "a"          # real item passes through
    assert await gen.__anext__() is None         # idle -> keepalive tick
    await gen.aclose()

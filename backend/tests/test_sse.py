"""Tests for the SSE transport encoder."""
from __future__ import annotations

import json

from app.sse import encode


def test_encode_wraps_payload_in_sse_frame() -> None:
    """Ensure encode produces a `data: <json>\\n\\n` frame."""
    frame = encode({"type": "system", "session_id": "s1", "raw": {}})
    text = frame.decode("utf-8")
    assert text.startswith("data: ")
    assert text.endswith("\n\n")
    payload = json.loads(text[len("data: ") :].strip())
    assert payload == {"type": "system", "session_id": "s1", "raw": {}}

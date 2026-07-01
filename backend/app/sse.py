"""Server-Sent Events transport encoding.

The only place that knows the SSE wire frame format. Services yield
event payload dicts; routers encode them here before streaming.
"""
from __future__ import annotations

import json


def encode(data: dict[str, object]) -> bytes:
    """
    Encode a payload dict as one SSE ``data:`` frame.

    :param data: The JSON-serialisable payload to send.
    :returns: A UTF-8 ``data: <json>\\n\\n`` SSE frame.
    """
    return ("data: " + json.dumps(data) + "\n\n").encode("utf-8")

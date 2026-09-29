"""Reading opencode's message payloads: tool-call inputs and assistant
errors. Pure; split out of ``opencode.py`` to keep it within the module
size limit."""
from __future__ import annotations

import json


def tool_summary(tool_input: object) -> str | None:
    """Summarise a tool call's input (file_path/path/command first)."""
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "command", "filePath"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return json.dumps(tool_input) if tool_input else None


def assistant_error(response: object) -> str | None:
    """Extract an OpenCode assistant error message from a message response."""
    if not isinstance(response, dict):
        return None
    info = response.get("info")
    if not isinstance(info, dict):
        return None
    error = info.get("error")
    if not isinstance(error, dict):
        return None
    data = error.get("data")
    if isinstance(data, dict) and isinstance(data.get("message"), str):
        return data["message"]
    name = error.get("name")
    return name if isinstance(name, str) else "unknown assistant error"

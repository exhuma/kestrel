"""Controlled Markdown and Atlassian Document Format conversion for Jira."""
from __future__ import annotations

from typing import Any


def to_text(value: object) -> str:
    """Normalize a Jira text string or ADF document into readable plain text."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    return "\n".join(_text_blocks(value)).strip()


def _text_blocks(node: dict[str, Any]) -> list[str]:
    """Extract visible text from an ADF node, preserving block boundaries."""
    content = node.get("content")
    if node.get("type") == "text":
        return [node.get("text", "")]
    if not isinstance(content, list):
        return ["---"] if node.get("type") == "rule" else []
    text = "".join("".join(_text_blocks(child)) for child in content)
    if node.get("type") in {"paragraph", "heading"}:
        return [text]
    if node.get("type") == "listItem":
        return [f"- {text}"]
    return [item for child in content for item in _text_blocks(child)]

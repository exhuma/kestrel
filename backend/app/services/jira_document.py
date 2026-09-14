"""Controlled Markdown and Atlassian Document Format conversion for Jira."""
from __future__ import annotations

import re
from typing import Any

_BULLET = re.compile(r"^- (.+)$")
_ORDERED = re.compile(r"^\d+\. (.+)$")
_HEADING = re.compile(r"^(#{1,6}) (.+)$")
_INLINE = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*)")


def to_adf(markdown: str) -> dict[str, Any]:
    """Convert Kestrel's controlled Markdown subset into a Jira ADF document."""
    blocks: list[dict[str, Any]] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line:
            index += 1
        elif line == "---":
            blocks.append({"type": "rule"})
            index += 1
        elif match := _HEADING.match(line):
            blocks.append(_heading(len(match.group(1)), match.group(2)))
            index += 1
        elif _BULLET.match(line):
            block, index = _list(lines, index, _BULLET, "bulletList")
            blocks.append(block)
        elif _ORDERED.match(line):
            block, index = _list(lines, index, _ORDERED, "orderedList")
            blocks.append(block)
        else:
            block, index = _paragraph(lines, index)
            blocks.append(block)
    return {"version": 1, "type": "doc", "content": blocks}


def to_text(value: object) -> str:
    """Normalize a Jira text string or ADF document into readable plain text."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    return "\n".join(_text_blocks(value)).strip()


def _heading(level: int, text: str) -> dict[str, Any]:
    """Build one ADF heading node with a bounded valid level."""
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": _inline(text),
    }


def _paragraph(lines: list[str], start: int) -> tuple[dict[str, Any], int]:
    """Build one paragraph, stopping before another supported block type."""
    paragraph: list[str] = []
    index = start
    while index < len(lines) and lines[index]:
        if index != start and _is_block(lines[index]):
            break
        paragraph.append(lines[index])
        index += 1
    block = {"type": "paragraph", "content": _inline("\n".join(paragraph))}
    return block, index


def _list(
    lines: list[str], start: int, pattern: re.Pattern[str], kind: str
) -> tuple[dict[str, Any], int]:
    """Build one flat ADF list from consecutive matching Markdown lines."""
    content: list[dict[str, Any]] = []
    index = start
    while index < len(lines):
        match = pattern.match(lines[index])
        if not match:
            break
        item = {
            "type": "listItem",
            "content": [_text_paragraph(match.group(1))],
        }
        content.append(item)
        index += 1
    return {"type": kind, "content": content}, index


def _is_block(line: str) -> bool:
    """Return whether a line begins a supported non-paragraph block."""
    return line == "---" or bool(
        _HEADING.match(line) or _BULLET.match(line) or _ORDERED.match(line)
    )


def _text_paragraph(text: str) -> dict[str, Any]:
    """Build an ADF paragraph from controlled inline Markdown."""
    return {"type": "paragraph", "content": _inline(text)}


def _inline(text: str) -> list[dict[str, Any]]:
    """Render supported inline code and bold syntax as ADF text nodes."""
    nodes: list[dict[str, Any]] = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("`"):
            nodes.append(_text(part[1:-1], "code"))
        elif part.startswith("**"):
            nodes.append(_text(part[2:-2], "strong"))
        else:
            nodes.append(_text(part))
    return nodes or [_text("")]


def _text(value: str, mark: str | None = None) -> dict[str, Any]:
    """Build one ADF text node, optionally carrying one inline mark."""
    node: dict[str, Any] = {"type": "text", "text": value}
    if mark:
        node["marks"] = [{"type": mark}]
    return node


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

"""Markdown-to-document parsing via markdown-it-py.

Converts arbitrary Markdown (including LLM-authored free-form content) into
a list of block dicts that ``app.documents`` converts to its closed construct
set. This module avoids importing from ``app.documents`` to prevent a circular
dependency; it returns plain dicts instead.
"""

from __future__ import annotations

import re
from typing import Any

from markdown_it import MarkdownIt

_TAG_RE = re.compile(r"<[^>]+>")


def parse_markdown_blocks(text: str) -> list[dict[str, Any]]:
    """Parse a Markdown string into a list of block descriptors.

    Each block dict has a ``type`` key and type-specific fields. The
    caller (``app.documents.parse_markdown``) converts these into the
    canonical construct set.

    :param text: A Markdown string; may be empty, yielding an empty list.
    :returns: A list of block descriptor dicts.
    """
    if not text:
        return []
    parser = MarkdownIt()
    return _parse_blocks(parser.parse(text))


def _parse_blocks(tokens: list[Any]) -> list[dict[str, Any]]:
    """Parse a sequence of markdown-it tokens into block descriptors."""
    blocks: list[dict[str, Any]] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open":
            level = int(token.tag[1])
            inline_token = tokens[i + 1]
            blocks.append({
                "type": "heading",
                "level": level,
                "inlines": _parse_inline(inline_token),
            })
            i += 3
        elif token.type == "paragraph_open":
            inline_token = tokens[i + 1]
            blocks.append({
                "type": "paragraph",
                "inlines": _parse_inline(inline_token),
            })
            i += 3
        elif token.type == "fence":
            blocks.append({
                "type": "code_block",
                "language": token.info,
                "text": token.content,
            })
            i += 1
        elif token.type == "hr":
            blocks.append({"type": "rule"})
            i += 1
        elif token.type in ("bullet_list_open", "ordered_list_open"):
            items, start_num, i = _parse_list_items(tokens, i)
            kind = "bullet" if token.type == "bullet_list_open" else "ordered"
            blocks.append({
                "type": f"{kind}_list",
                "start": start_num,
                "items": items,
            })
        elif token.type == "html_block":
            text = _strip_html_tags(token.content)
            if text:
                blocks.append({"type": "paragraph", "inlines": [
                    {"kind": "text", "text": text},
                ]})
            i += 1
        else:
            i += 1
    return blocks


def _parse_list_items(
    tokens: list[Any], start: int
) -> tuple[list[dict[str, Any]], int, int]:
    """Collect items from a list token sequence.

    :returns: The list of item dicts, the start number for ordered lists,
        and the index past the list's closing token.
    """
    items: list[dict[str, Any]] = []
    start_num = 1
    i = start + 1
    if tokens[start].type == "ordered_list_open" and i < len(tokens):
        first_item_info = getattr(tokens[i], "info", "") or ""
        if first_item_info.isdigit():
            start_num = int(first_item_info)
    close_type = (
        "bullet_list_close"
        if tokens[start].type == "bullet_list_open"
        else "ordered_list_close"
    )
    while i < len(tokens) and tokens[i].type != close_type:
        if tokens[i].type == "list_item_open":
            paragraphs, i = _parse_item_paragraphs(tokens, i + 1)
            items.append({"paragraphs": paragraphs})
        else:
            i += 1
    return items, start_num, i + 1


def _parse_item_paragraphs(
    tokens: list[Any], start: int
) -> tuple[list[dict[str, Any]], int]:
    """Collect all paragraphs within one list item.

    :returns: The list of paragraph dicts and the index of the
        ``list_item_close`` token (caller advances past it).
    """
    paragraphs: list[dict[str, Any]] = []
    i = start
    while i < len(tokens) and tokens[i].type != "list_item_close":
        if tokens[i].type == "paragraph_open":
            paragraphs.append({"inlines": _parse_inline(tokens[i + 1])})
            i += 3
        else:
            i += 1
    return paragraphs, i


def _parse_inline(token: Any) -> list[dict[str, str]]:
    """Parse a markdown-it inline token into a list of inline descriptors."""
    return _parse_inline_children(token.children or [])


def _parse_inline_children(
    children: list[Any],
) -> list[dict[str, str]]:
    """Walk inline child tokens, building a flat list of inlines.

    ``strong_open``/``em_open`` push a mark onto a stack; text runs inherit
    the innermost mark (or are plain text). ``link_open`` collects its
    children into a link descriptor. ``code_inline`` becomes code.
    """
    inlines: list[dict[str, str]] = []
    mark_stack: list[str] = []
    link_href: str | None = None
    link_children: list[Any] = []

    for child in children:
        _push_mark(child, mark_stack)
        if child.type == "link_open":
            link_href = _link_href(child)
            link_children = []
        elif child.type == "link_close" and link_href is not None:
            inner = _parse_inline_children(link_children)
            inlines.append({
                "kind": "link",
                "href": link_href,
                "text": _inline_text(inner),
            })
            link_href = None
        else:
            _emit_inline_child(
                child, inlines, mark_stack, link_href, link_children,
            )

    return inlines


def _push_mark(child: Any, mark_stack: list[str]) -> None:
    """Push or pop a formatting mark based on the token type."""
    if child.type == "strong_open":
        mark_stack.append("strong")
    elif child.type == "em_open":
        mark_stack.append("em")
    elif child.type in ("strong_close", "em_close"):
        mark_stack.pop()


def _emit_inline_child(
    child: Any,
    inlines: list[dict[str, str]],
    mark_stack: list[str],
    link_href: str | None,
    link_children: list[Any],
) -> None:
    """Emit code or text tokens into the inline list."""
    if child.type == "code_inline":
        inlines.append({"kind": "code", "text": child.content})
        return
    if child.type != "text" or not child.content:
        return
    if link_href is not None:
        link_children.append(child)
        return
    mark = mark_stack[-1] if mark_stack else None
    inlines.append(_mark_text(child.content, mark))


def _link_href(token: Any) -> str:
    """Extract the href from a link_open token's attrs dict."""
    attrs = getattr(token, "attrs", None) or {}
    return attrs.get("href", "") if isinstance(attrs, dict) else ""


def _mark_text(text: str, mark: str | None) -> dict[str, str]:
    """Wrap a text run in the appropriate inline descriptor for its mark."""
    kind = "strong" if mark == "strong" else (
        "emphasis" if mark == "em" else "text"
    )
    return {"kind": kind, "text": text}


def _inline_text(inlines: list[dict[str, str]]) -> str:
    """Concatenate the visible text of an inline sequence."""
    return "".join(inline.get("text", "") for inline in inlines)


def _strip_html_tags(text: str) -> str:
    """Remove HTML/XML tags from a string, preserving inner text.

    Used for ``html_block`` tokens that contain LLM-emitted delimiter
    tags (e.g. ``<UNDERSTING>content</UNDERSTING>``). Returns the
    stripped and trimmed text, or an empty string if nothing remains.
    """
    return _TAG_RE.sub("", text).strip()

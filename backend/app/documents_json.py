"""JSON (de)serialization for canonical documents.

The closed JSON payload is a versioned, self-describing structure that
round-trips through :func:`document_json` / :func:`parse_document_json`.
Only the closed construct set defined in ``app.documents`` appears in the
output; link targets are passed through verbatim so the client can apply
its own protocol policy (e.g. restricting clickable links to http/https).
"""

from __future__ import annotations

from typing import cast

from app.documents import (
    Block,
    BulletList,
    Code,
    CodeBlock,
    Document,
    Emphasis,
    Heading,
    Inline,
    Link,
    ListItem,
    OrderedList,
    Paragraph,
    Rule,
    Strong,
    Text,
)

__all__ = [
    "document_json",
    "parse_document_json",
]


def document_json(value: Document) -> dict[str, object]:
    """Serialize a canonical document into its closed JSON representation.

    The output is a versioned, self-describing payload that round-trips
    through :func:`parse_document_json`. Only the closed construct set
    defined in ``app.documents`` appears in the output; link targets are
    passed through verbatim so the client can apply its own protocol
    policy (e.g. restricting clickable links to http/https).

    :param value: A validated canonical document.
    :returns: ``{"version": 1, "blocks": [...]}`` where each block is a
        small dict with a ``type`` discriminator and type-specific fields.
    """
    return {
        "version": 1,
        "blocks": [_json_block(block) for block in value.blocks],
    }


def parse_document_json(payload: dict[str, object]) -> Document:
    """Deserialize a closed JSON payload into a canonical document.

    The inverse of :func:`document_json`. Validates the version and block
    structure; raises ``ValueError`` on malformed or unsupported payloads.

    :param payload: A dict as produced by :func:`document_json`.
    :returns: A validated ``Document``.
    :raises ValueError: If the payload is not a valid document JSON object.
    """
    if not isinstance(payload, dict):
        raise ValueError("document payload must be an object")
    version = payload.get("version")
    if version != 1:
        raise ValueError(f"unsupported document version: {version!r}")
    raw_blocks = payload.get("blocks")
    if not isinstance(raw_blocks, list):
        raise ValueError("document blocks must be a list")
    blocks = tuple(_block_from_json(b) for b in raw_blocks)
    return Document(blocks)


def _block_from_json(raw: object) -> Block:
    """Deserialize one block dict into a canonical Block construct."""
    if not isinstance(raw, dict):
        raise ValueError("block must be an object")
    btype = str(raw.get("type", ""))
    if btype == "heading":
        return Heading(
            int(cast(int, raw["level"])),
            _inlines_from_json(raw["content"]),
        )
    if btype == "paragraph":
        return Paragraph(_inlines_from_json(raw["content"]))
    if btype == "code_block":
        return CodeBlock(
            language=str(raw.get("language") or ""),
            text=str(raw.get("text", "")),
        )
    if btype == "rule":
        return Rule()
    if btype in ("bullet_list", "ordered_list"):
        return _list_from_json(raw)
    raise ValueError(f"unknown block type: {btype!r}")


def _list_from_json(
    raw: dict[str, object],
) -> BulletList | OrderedList:
    """Build a list block from its JSON representation."""
    start_raw = raw.get("start")
    start = int(cast(int, start_raw)) if start_raw is not None else 1
    items_raw = cast(list[dict[str, object]], raw["items"])
    items = tuple(
        ListItem(tuple(
            Paragraph(_inlines_from_json(p["content"]))
            for p in cast(list[dict[str, object]], item["paragraphs"])
        ))
        for item in items_raw
    )
    if str(raw.get("type", "")) == "ordered_list":
        return OrderedList(start=start, items=items)
    return BulletList(items=items)


def _inlines_from_json(raw: object) -> tuple[Inline, ...]:
    """Deserialize a list of inline dicts into Inline constructs."""
    if not isinstance(raw, list):
        raise ValueError("inline content must be a list")
    result: list[Inline] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("inline must be an object")
        kind = str(item.get("type", ""))
        if kind == "text":
            result.append(Text(value=str(item["text"])))
        elif kind == "strong":
            result.append(Strong(value=str(item["text"])))
        elif kind == "emphasis":
            result.append(Emphasis(value=str(item["text"])))
        elif kind == "code":
            result.append(Code(value=str(item["text"])))
        elif kind == "link":
            href = str(item["href"])
            text = str(item.get("text", ""))
            result.append(Link(href=href, value=text))
        else:
            raise ValueError(f"unknown inline type: {kind!r}")
    return tuple(result)


def _json_block(block: Block) -> dict[str, object]:
    """Render one canonical block as a JSON-serialisable dict."""
    if isinstance(block, Heading):
        return {
            "type": "heading",
            "level": block.level,
            "content": [_json_inline(i) for i in block.content],
        }
    if isinstance(block, Paragraph):
        return {
            "type": "paragraph",
            "content": [_json_inline(i) for i in block.content],
        }
    if isinstance(block, CodeBlock):
        return {
            "type": "code_block",
            "language": block.language or None,
            "text": block.text.rstrip(),
        }
    if isinstance(block, Rule):
        return {"type": "rule"}
    ordered = isinstance(block, OrderedList)
    return {
        "type": "ordered_list" if ordered else "bullet_list",
        "start": block.start if ordered else None,
        "items": [
            {
                "paragraphs": [
                    {"content": [_json_inline(i) for i in p.content]}
                    for p in item.content
                ]
            }
            for item in block.items
        ],
    }


def _json_inline(inline: Inline) -> dict[str, object]:
    """Render one inline construct as a JSON-serialisable dict."""
    if isinstance(inline, Link):
        return {
            "type": "link",
            "href": inline.href,
            "text": inline.value or inline.href,
        }
    kind = (
        "strong"
        if isinstance(inline, Strong)
        else "emphasis"
        if isinstance(inline, Emphasis)
        else "code"
        if isinstance(inline, Code)
        else "text"
    )
    return {"type": kind, "text": inline.value}

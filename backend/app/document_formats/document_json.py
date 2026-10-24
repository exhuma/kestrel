"""Document JSON: how documents are stored (the persistence boundary).

A versioned, self-describing payload over the closed set.
:func:`parse_document_json` is the validating inverse of
:func:`document_json`; the ``*_document`` pair works on JSON text, as a
database column holds it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import cast

from app.documents import (
    Block,
    BulletList,
    Cell,
    Code,
    CodeBlock,
    Document,
    Emphasis,
    HardBreak,
    Heading,
    Image,
    Inline,
    Link,
    ListItem,
    Marker,
    Mention,
    OrderedList,
    Paragraph,
    Rule,
    Strong,
    Table,
    Text,
    validate_document,
)

_VERSION = 1
Json = dict[str, object]


def document_json(value: Document) -> Json:
    """Serialise a document into its JSON payload."""
    return {"version": _VERSION,
            "blocks": [_dump_block(block) for block in value.blocks]}


def parse_document_json(payload: object) -> Document:
    """Deserialise and validate a JSON payload.

    :raises ValueError: If it is not a valid document payload.
    """
    if not isinstance(payload, dict):
        raise ValueError("document payload must be an object")
    if payload.get("version") != _VERSION:
        raise ValueError(f"unsupported version: {payload.get('version')!r}")
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError("document blocks must be a list")
    try:
        return validate_document(
            Document(tuple(_load_block(block) for block in blocks))
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"malformed document payload: {exc}") from exc


def dump_document(value: Document) -> str:
    """A document as JSON text."""
    return json.dumps(document_json(value), ensure_ascii=False)


def load_document(text: str) -> Document:
    """A document from JSON text.

    :raises ValueError: If the text is not a document payload.
    """
    return parse_document_json(json.loads(text))


def _dump_block(block: Block) -> Json:
    if isinstance(block, Heading):
        return {"type": "heading", "level": block.level,
                "content": _dump_inlines(block.content)}
    if isinstance(block, Paragraph):
        return {"type": "paragraph", "content": _dump_inlines(block.content)}
    if isinstance(block, (BulletList, OrderedList)):
        return _dump_list(block)
    if isinstance(block, Table):
        return {"type": "table",
                "header": [_dump_inlines(cell) for cell in block.header],
                "rows": [[_dump_inlines(cell) for cell in row]
                         for row in block.rows]}
    return _dump_leaf(block)


def _dump_leaf(block: CodeBlock | Image | Rule | Marker) -> Json:
    if isinstance(block, CodeBlock):
        return {"type": "code_block", "language": block.language,
                "text": block.text}
    if isinstance(block, Image):
        return {"type": "image", "src": block.src, "alt": block.alt}
    if isinstance(block, Marker):
        return {"type": "marker", "name": block.name}
    return {"type": "rule"}


def _dump_list(block: BulletList | OrderedList) -> Json:
    payload: Json = {
        "type": "bullet_list" if isinstance(block, BulletList)
        else "ordered_list",
        "items": [{"content": [_dump_block(part) for part in item.content]}
                  for item in block.items],
    }
    if isinstance(block, OrderedList):
        payload["start"] = block.start
    return payload


def _dump_inlines(content: tuple[Inline, ...]) -> list[Json]:
    return [_dump_inline(inline) for inline in content]


def _dump_inline(inline: Inline) -> Json:
    if isinstance(inline, Link):
        return {"type": "link", "href": inline.href, "text": inline.value}
    if isinstance(inline, Mention):
        return {"type": "mention", "account_id": inline.account_id,
                "display_name": inline.display_name}
    if isinstance(inline, HardBreak):
        return {"type": "hard_break"}
    return {"type": _INLINE_NAMES[type(inline)], "text": inline.value}


_INLINE_NAMES: dict[type, str] = {
    Text: "text", Strong: "strong", Emphasis: "emphasis", Code: "code",
}


def _load_block(raw: object) -> Block:
    raw = _object(raw)
    loader = _BLOCK_LOADERS.get(str(raw.get("type")))
    if loader is None:
        raise ValueError(f"unknown block type: {raw.get('type')!r}")
    return loader(raw)


def _load_list(raw: Json) -> BulletList | OrderedList:
    items = tuple(
        ListItem(tuple(
            cast("Paragraph | BulletList | OrderedList", _load_block(part))
            for part in _list(_object(item)["content"])
        ))
        for item in _list(raw["items"])
    )
    if raw["type"] == "ordered_list":
        return OrderedList(int(cast(int, raw.get("start", 1))), items)
    return BulletList(items)


def _load_table(raw: Json) -> Table:
    return Table(
        tuple(_load_inlines(cell) for cell in _list(raw["header"])),
        tuple(tuple(_load_inlines(cell) for cell in _list(row))
              for row in _list(raw["rows"])),
    )


_BLOCK_LOADERS: dict[str, Callable[[Json], Block]] = {
    "heading": lambda raw: Heading(int(cast(int, raw["level"])),
                                   _load_inlines(raw["content"])),
    "paragraph": lambda raw: Paragraph(_load_inlines(raw["content"])),
    "code_block": lambda raw: CodeBlock(str(raw.get("language") or ""),
                                        str(raw.get("text") or "")),
    "bullet_list": _load_list,
    "ordered_list": _load_list,
    "image": lambda raw: Image(str(raw["src"]), str(raw.get("alt") or "")),
    "table": _load_table,
    "rule": lambda _raw: Rule(),
    "marker": lambda raw: Marker(str(raw["name"])),
}


def _load_inlines(raw: object) -> Cell:
    return tuple(_load_inline(_object(item)) for item in _list(raw))


def _load_inline(raw: Json) -> Inline:
    kind = raw.get("type")
    if kind == "link":
        return Link(str(raw["href"]), str(raw.get("text") or ""))
    if kind == "mention":
        return Mention(str(raw["account_id"]),
                       str(raw.get("display_name") or ""))
    if kind == "hard_break":
        return HardBreak()
    inline_type = next(
        (t for t, name in _INLINE_NAMES.items() if name == kind), None
    )
    if inline_type is None:
        raise ValueError(f"unknown inline type: {kind!r}")
    return inline_type(str(raw["text"]))


def _object(raw: object) -> Json:
    if not isinstance(raw, dict):
        raise ValueError("expected an object")
    return raw


def _list(raw: object) -> list:
    if not isinstance(raw, list):
        raise ValueError("expected a list")
    return raw

"""Jira ADF → :class:`~app.documents.Document` (contracts/adf-mapping.md).

Total over ADF: nothing raises, and unknown structure degrades to its
text. Containers the closed set lacks (panel, expand, blockquote, layout)
keep their children; several marks on one text keep the strongest (link,
then code, strong, emphasis). A string — what Jira Server returns — is
kept as plain paragraphs. The result is always a valid document.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

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
    normalise_inlines,
    validate_document,
)

_MARKER = re.compile(r"^\[kestrel:([a-z0-9][a-z0-9_-]*)\]$")
_CONTAINERS = frozenset({
    "panel", "expand", "nestedExpand", "blockquote", "layoutSection",
    "layoutColumn", "bodiedExtension", "doc",
})
_INLINE_TYPES = frozenset({
    "text", "mention", "hardBreak", "emoji", "inlineCard", "status", "date",
    "mediaInline", "placeholder",
})
_MAX_HEADING_LEVEL = 6

Node = dict


def parse_adf(value: object) -> Document:
    """Parse an ADF document (or Jira Server's plain string)."""
    if isinstance(value, str):
        return validate_document(Document(tuple(_plain(value))))
    return validate_document(Document(tuple(_blocks(_children(value)))))


def _plain(text: str) -> Iterator[Paragraph]:
    for chunk in re.split(r"\n\s*\n", text.strip()):
        lines = [line for line in chunk.splitlines() if line.strip()]
        content: list[Inline] = []
        for index, line in enumerate(lines):
            content += [HardBreak()] if index else []
            content.append(Text(line))
        if content:
            yield Paragraph(tuple(content))


def _children(node: object) -> list[Node]:
    content = node.get("content") if isinstance(node, dict) else None
    if not isinstance(content, list):
        return []
    return [child for child in content if isinstance(child, dict)]


def _attrs(node: Node) -> dict:
    attrs = node.get("attrs")
    return attrs if isinstance(attrs, dict) else {}


def _blocks(nodes: list[Node]) -> Iterator[Block]:
    for node in nodes:
        yield from _block(node)


def _block(node: Node) -> Iterator[Block]:
    handler = _BLOCK_HANDLERS.get(str(node.get("type")))
    if handler is not None:
        yield from handler(node)
    elif node.get("type") in _CONTAINERS:
        yield from _blocks(_children(node))
    else:
        yield from _unknown(node)


def _paragraph(node: Node) -> Iterator[Block]:
    marker = _marker(node)
    if marker is not None:
        yield marker
        return
    content = _inlines(_children(node))
    if content:
        yield Paragraph(content)


def _marker(node: Node) -> Marker | None:
    children = _children(node)
    if len(children) != 1 or _strongest_mark(children[0]) != "code":
        return None
    match = _MARKER.match(str(children[0].get("text", "")))
    return Marker(match.group(1)) if match else None


def _heading(node: Node) -> Iterator[Block]:
    content = _inlines(_children(node))
    level = _attrs(node).get("level")
    if content:
        level = level if isinstance(level, int) else 1
        yield Heading(min(max(level, 1), _MAX_HEADING_LEVEL), content)


def _code_block(node: Node) -> Iterator[Block]:
    language = _attrs(node).get("language")
    yield CodeBlock(language if isinstance(language, str) else "",
                    _visible(node))


def _rule(_node: Node) -> Iterator[Block]:
    yield Rule()


def _list(node: Node) -> Iterator[Block]:
    items = tuple(
        item for item in (_item(child) for child in _children(node)) if item
    )
    if not items:
        return
    if node.get("type") == "bulletList":
        yield BulletList(items)
    else:
        order = _attrs(node).get("order")
        yield OrderedList(order if isinstance(order, int) else 1, items)


def _item(node: Node) -> ListItem | None:
    parts: list[Paragraph | BulletList | OrderedList] = []
    for block in _blocks(_children(node)):
        if isinstance(block, (Paragraph, BulletList, OrderedList)):
            parts.append(block)
        elif isinstance(block, CodeBlock) and block.text.strip():
            parts.append(Paragraph((Code(block.text.strip()),)))
    return ListItem(tuple(parts)) if parts else None


def _table(node: Node) -> Iterator[Block]:
    rows = [
        tuple(_cell(cell) for cell in _children(row))
        for row in _children(node)
    ]
    rows = [row for row in rows if row]
    if not rows:
        return
    width = len(rows[0])
    yield Table(rows[0], tuple((row + ((),) * width)[:width]
                               for row in rows[1:]))


def _cell(node: Node) -> Cell:
    content: list[Inline] = []
    for block in _children(node):
        content += [HardBreak()] if content else []
        content += list(_inlines(_children(block)) or _as_text(block))
    return normalise_inlines(content)


def _as_text(node: Node) -> tuple[Inline, ...]:
    text = _visible(node)
    return (Text(text),) if text else ()


def _media(node: Node) -> Iterator[Block]:
    for media in _children(node):
        attrs = _attrs(media)
        alt = str(attrs.get("alt") or "")
        url = attrs.get("url")
        if attrs.get("type") == "external" and isinstance(url, str) and url:
            yield Image(url, alt)
        elif alt:
            yield Paragraph((Text(alt),))


def _unknown(node: Node) -> Iterator[Block]:
    """An unknown node: inline children make a paragraph, else recurse."""
    children = _children(node)
    if children and all(c.get("type") in _INLINE_TYPES for c in children):
        content = _inlines(children)
        if content:
            yield Paragraph(content)
    elif children:
        yield from _blocks(children)
    elif isinstance(node.get("text"), str) and node["text"]:
        yield Paragraph((Text(node["text"]),))


_BLOCK_HANDLERS: dict[str, Callable[[Node], Iterator[Block]]] = {
    "paragraph": _paragraph,
    "heading": _heading,
    "codeBlock": _code_block,
    "rule": _rule,
    "bulletList": _list,
    "orderedList": _list,
    "table": _table,
    "mediaSingle": _media,
    "mediaGroup": _media,
}


def _inlines(nodes: list[Node]) -> tuple[Inline, ...]:
    return normalise_inlines(
        inline for node in nodes for inline in _inline(node)
    )


def _inline(node: Node) -> Iterator[Inline]:
    kind = node.get("type")
    attrs = _attrs(node)
    if kind == "text":
        yield from _text(node)
    elif kind == "mention" and attrs.get("id"):
        name = str(attrs.get("text") or "").removeprefix("@")
        yield Mention(str(attrs["id"]), name)
    elif kind == "hardBreak":
        yield HardBreak()
    elif kind == "inlineCard" and attrs.get("url"):
        yield Link(str(attrs["url"]), str(attrs["url"]))
    elif kind in ("emoji", "status"):
        yield Text(str(attrs.get("text") or attrs.get("shortName") or ""))


def _text(node: Node) -> Iterator[Inline]:
    text = node.get("text")
    if not isinstance(text, str) or not text:
        return
    mark = _strongest_mark(node)
    if mark == "link":
        yield Link(_link_href(node), text)
    else:
        yield {"code": Code, "strong": Strong, "em": Emphasis}.get(
            mark or "", Text
        )(text)


def _marks(node: Node) -> list[dict]:
    marks = node.get("marks")
    if not isinstance(marks, list):
        return []
    return [m for m in marks if isinstance(m, dict)]


def _strongest_mark(node: Node) -> str | None:
    kinds = {m.get("type") for m in _marks(node)}
    return next(
        (k for k in ("link", "code", "strong", "em") if k in kinds), None
    )


def _link_href(node: Node) -> str:
    for mark in _marks(node):
        if mark.get("type") == "link":
            return str(_attrs(mark).get("href") or "")
    return ""


def _visible(node: Node) -> str:
    if node.get("type") == "text":
        return str(node.get("text") or "")
    return "".join(_visible(child) for child in _children(node))

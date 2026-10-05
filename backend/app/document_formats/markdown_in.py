"""Markdown → :class:`~app.documents.Document`.

Uses markdown-it-py's CommonMark preset plus GFM tables. Constructs the
closed set cannot hold degrade to their text: a blockquote's blocks are
kept unquoted, nested marks keep the outermost, HTML keeps only its text
(except a ``<!-- kestrel:NAME -->`` comment, which is a marker), and a
block inside a list item other than a paragraph or list becomes a
paragraph of its text. The result is always a valid document.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

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
    OrderedList,
    Paragraph,
    Rule,
    Strong,
    Table,
    Text,
    normalise_inlines,
    validate_document,
)

_MARKER_COMMENT = re.compile(r"^<!--\s*kestrel:([a-z0-9][a-z0-9_-]*)\s*-->$")
_TAG = re.compile(r"<[^>]+>")
_PARSER = MarkdownIt("commonmark").enable("table")

#: One paragraph's content before it is split around its images.
_Piece = Inline | Image


def parse_markdown(text: str) -> Document:
    """Parse Markdown into a valid document (empty text, empty document)."""
    if not text:
        return Document(())
    root = SyntaxTreeNode(_PARSER.parse(text))
    return validate_document(Document(tuple(_blocks(root.children))))


def _blocks(nodes: list[SyntaxTreeNode]) -> Iterator[Block]:
    for node in nodes:
        yield from _block(node)


def _block(node: SyntaxTreeNode) -> Iterator[Block]:
    """The blocks one syntax node stands for (none, one or several)."""
    kind = node.type
    if kind == "paragraph":
        yield from _paragraph(node)
    elif kind == "heading":
        content = _merge(_inlines(node.children[0]))
        if content:
            yield Heading(int(node.tag[1]), content)
    elif kind in ("fence", "code_block"):
        yield CodeBlock(node.info.strip() if kind == "fence" else "",
                        node.content)
    elif kind == "hr":
        yield Rule()
    elif kind in ("bullet_list", "ordered_list"):
        yield from _list(node)
    elif kind == "table":
        yield from _table(node)
    elif kind == "blockquote":
        yield from _blocks(node.children)
    elif kind == "html_block":
        yield from _html(node.content)


def _paragraph(node: SyntaxTreeNode) -> Iterator[Block]:
    """A paragraph, split into paragraphs and images around each image."""
    run: list[Inline] = []
    for piece in _inlines(node.children[0], images=True):
        if isinstance(piece, Image):
            yield from _flush(run)
            yield piece
        else:
            run.append(piece)
    yield from _flush(run)


def _flush(run: list[Inline]) -> Iterator[Paragraph]:
    content = _merge(run)
    run.clear()
    if content:
        yield Paragraph(content)


def _inlines(node: SyntaxTreeNode, images: bool = False) -> Iterator[_Piece]:
    """The inline content of an ``inline`` node, flattened."""
    for child in node.children:
        yield from _inline(child, images)


def _inline(node: SyntaxTreeNode, images: bool) -> Iterator[_Piece]:
    kind = node.type
    if kind == "text":
        yield Text(node.content)
    elif kind == "softbreak":
        yield Text(" ")
    elif kind == "hardbreak":
        yield HardBreak()
    elif kind == "code_inline":
        yield Code(node.content)
    elif kind in ("strong", "em"):
        text = _visible(node)
        if text:
            yield Strong(text) if kind == "strong" else Emphasis(text)
    elif kind == "link":
        yield Link(str(node.attrs.get("href", "")), _visible(node))
    elif kind == "image":
        yield from _image(node, images)
    elif kind == "html_inline":
        yield Text(_TAG.sub("", node.content))


def _image(node: SyntaxTreeNode, images: bool) -> Iterator[_Piece]:
    src, alt = str(node.attrs.get("src", "")), node.content
    if images and src:
        yield Image(src, alt)
    elif alt:
        yield Text(alt)


def _visible(node: SyntaxTreeNode) -> str:
    """All text below *node*, marks dropped."""
    if node.type in ("text", "code_inline"):
        return node.content
    if node.type == "softbreak":
        return " "
    return "".join(_visible(child) for child in node.children)


def _merge(pieces: Iterable[_Piece]) -> tuple[Inline, ...]:
    """Valid inline content; an image inside a heading or cell keeps its
    alt text."""
    return normalise_inlines(
        Text(piece.alt) if isinstance(piece, Image) else piece
        for piece in pieces
    )


def _list(node: SyntaxTreeNode) -> Iterator[BulletList | OrderedList]:
    items = tuple(
        item for item in (_item(child) for child in node.children) if item
    )
    if not items:
        return
    if node.type == "bullet_list":
        yield BulletList(items)
    else:
        yield OrderedList(int(node.attrs.get("start", 1)), items)


def _item(node: SyntaxTreeNode) -> ListItem | None:
    parts: list[Paragraph | BulletList | OrderedList] = []
    for block in _blocks(node.children):
        if isinstance(block, (Paragraph, BulletList, OrderedList)):
            parts.append(block)
        elif isinstance(block, CodeBlock) and block.text.strip():
            parts.append(Paragraph((Code(block.text.strip()),)))
    return ListItem(tuple(parts)) if parts else None


def _table(node: SyntaxTreeNode) -> Iterator[Table]:
    rows = [
        tuple(_cell(cell) for cell in row.children)
        for section in node.children
        for row in section.children
    ]
    if not rows or not rows[0]:
        return
    width = len(rows[0])
    body = tuple(_pad(row, width) for row in rows[1:])
    yield Table(rows[0], body)


def _cell(node: SyntaxTreeNode) -> Cell:
    if not node.children:
        return ()
    return _merge(_inlines(node.children[0]))


def _pad(row: tuple[Cell, ...], width: int) -> tuple[Cell, ...]:
    return (row + ((),) * width)[:width]


def _html(content: str) -> Iterator[Block]:
    marker = _MARKER_COMMENT.match(content.strip())
    if marker:
        yield Marker(marker.group(1))
        return
    text = _TAG.sub("", content).strip()
    if text:
        yield Paragraph((Text(text),))

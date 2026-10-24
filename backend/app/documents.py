"""Source-neutral documents: the closed set of constructs (Principle VI).

Every document kestrel handles — ticket bodies, comments, change-request
bodies, artifacts, agent-authored text — is a :class:`Document` built from
the constructs below. This module knows no platform format: parsing into a
document and rendering out of one live in ``app.document_formats``, used
only by the adapter at each system boundary (constitution Principle VI).

Core code builds documents with :func:`document` and :func:`paragraph`,
which validate; a parser that builds constructs directly validates its
result with :func:`validate_document`. A consumer that needs plain text
asks the document (:meth:`Document.plain_text`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class Text:
    """Unformatted inline text whose value must be nonempty."""

    value: str


@dataclass(frozen=True)
class Strong:
    """Inline text emphasized as strong content."""

    value: str


@dataclass(frozen=True)
class Emphasis:
    """Inline text emphasized as italic content."""

    value: str


@dataclass(frozen=True)
class Code:
    """Inline text rendered as code and intended for direct copying."""

    value: str


@dataclass(frozen=True)
class Link:
    """A hyperlink; ``value`` is its text, or the target when empty."""

    href: str
    value: str = ""


@dataclass(frozen=True)
class Mention:
    """A person, by their account on the target system (feature 046)."""

    account_id: str
    display_name: str = ""


@dataclass(frozen=True)
class HardBreak:
    """A line break inside a paragraph."""


Inline: TypeAlias = Text | Strong | Emphasis | Code | Link | Mention | HardBreak
#: One table cell: its inline content, which may be empty.
Cell: TypeAlias = tuple[Inline, ...]

_MAX_HEADING_LEVEL = 6
_MARKER_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class Heading:
    """A heading with a level from one through six."""

    level: int
    content: tuple[Inline, ...]


@dataclass(frozen=True)
class Paragraph:
    """A paragraph holding a flat sequence of inline content."""

    content: tuple[Inline, ...]


@dataclass(frozen=True)
class CodeBlock:
    """A fenced code block with an optional language tag."""

    language: str = ""
    text: str = ""


@dataclass(frozen=True)
class ListItem:
    """One list item: paragraphs, and lists nested in it."""

    content: tuple[Paragraph | BulletList | OrderedList, ...]


@dataclass(frozen=True)
class BulletList:
    """A sequence of list items."""

    items: tuple[ListItem, ...]


@dataclass(frozen=True)
class OrderedList:
    """A sequence of list items numbered from ``start``."""

    start: int = 1
    items: tuple[ListItem, ...] = ()


@dataclass(frozen=True)
class Image:
    """An image by its URL, with alternative text."""

    src: str
    alt: str = ""


@dataclass(frozen=True)
class Table:
    """A table: one header row and body rows of the same width."""

    header: tuple[Cell, ...]
    rows: tuple[tuple[Cell, ...], ...] = ()


@dataclass(frozen=True)
class Rule:
    """A thematic break between document sections."""


@dataclass(frozen=True)
class Marker:
    """Machine-readable ownership or correlation mark, e.g. ``posted``.

    Each adapter decides how it looks on its platform; core code only
    adds and checks markers by name.
    """

    name: str


Block: TypeAlias = (
    Heading | Paragraph | CodeBlock | BulletList | OrderedList | Image
    | Table | Rule | Marker
)


@dataclass(frozen=True)
class Document:
    """An immutable ordered collection of source-neutral content blocks."""

    blocks: tuple[Block, ...]

    def plain_text(self) -> str:
        """The visible text, one line per block or list item; no markers."""
        return "\n".join(
            line for block in self.blocks for line in _text_lines(block)
        )

    def markers(self) -> frozenset[str]:
        """The names of the markers this document carries."""
        return frozenset(
            block.name for block in self.blocks if isinstance(block, Marker)
        )

    def mentions(self) -> frozenset[str]:
        """The account ids of everyone this document mentions."""
        return frozenset(
            inline.account_id
            for inline in _all_inlines(self.blocks)
            if isinstance(inline, Mention)
        )


#: The document with nothing in it.
EMPTY_DOCUMENT = Document(())


def document(*blocks: Block) -> Document:
    """Build and validate a document from the supplied content blocks."""
    return validate_document(Document(blocks))


def paragraph(*content: Inline) -> Paragraph:
    """Build a nonempty paragraph from explicitly typed inline content."""
    _validate_inlines(content)
    return Paragraph(content)


def validate_document(value: Document) -> Document:
    """Return *value* if every block is valid.

    :raises ValueError: On the first invalid construct.
    """
    for block in value.blocks:
        _validate_block(block)
    return value


def _validate_block(block: Block) -> None:
    """Reject a block that not every renderer can represent."""
    if isinstance(block, Heading):
        if not 1 <= block.level <= _MAX_HEADING_LEVEL:
            raise ValueError("heading level must be between 1 and 6")
        _validate_inlines(block.content)
    elif isinstance(block, Paragraph):
        _validate_inlines(block.content)
    elif isinstance(block, (BulletList, OrderedList)):
        _validate_list(block)
    elif isinstance(block, Table):
        _validate_table(block)
    elif isinstance(block, Image) and not block.src:
        raise ValueError("an image needs a source")
    elif isinstance(block, Marker) and not _MARKER_NAME.match(block.name):
        raise ValueError(f"invalid marker name: {block.name!r}")


def _validate_list(block: BulletList | OrderedList) -> None:
    if not block.items:
        raise ValueError("lists require at least one item")
    for item in block.items:
        if not item.content:
            raise ValueError("list items require content")
        for part in item.content:
            _validate_block(part)


def _validate_table(block: Table) -> None:
    if not block.header:
        raise ValueError("a table needs a header")
    if any(len(row) != len(block.header) for row in block.rows):
        raise ValueError("every table row needs one cell per header")
    for cell in (*block.header, *(c for row in block.rows for c in row)):
        for inline in cell:
            _validate_inline(inline)


def _validate_inlines(content: tuple[Inline, ...]) -> None:
    if not content:
        raise ValueError("text content must be nonempty")
    for inline in content:
        _validate_inline(inline)


def _validate_inline(inline: Inline) -> None:
    if isinstance(inline, Link):
        valid = bool(inline.href)
    elif isinstance(inline, Mention):
        valid = bool(inline.account_id)
    elif isinstance(inline, HardBreak):
        valid = True
    else:
        valid = bool(inline.value)
    if not valid:
        raise ValueError("text content must be nonempty")


def normalise_inlines(pieces: Iterable[Inline]) -> tuple[Inline, ...]:
    """*pieces* as valid inline content: adjacent plain text joined, empty
    text dropped, a link without a target kept as its text. For parsers."""
    merged: list[Inline] = []
    for inline in (_valid_inline(piece) for piece in pieces):
        if inline is None:
            continue
        if isinstance(inline, Text) and merged and isinstance(merged[-1], Text):
            merged[-1] = Text(merged[-1].value + inline.value)
        else:
            merged.append(inline)
    return tuple(merged)


def _valid_inline(inline: Inline) -> Inline | None:
    if isinstance(inline, Link) and not inline.href:
        inline = Text(inline.value)
    if isinstance(inline, (Text, Strong, Emphasis, Code)) and not inline.value:
        return None
    if isinstance(inline, Mention) and not inline.account_id:
        return None
    return inline


def inline_text(inline: Inline) -> str:
    """One inline's visible text."""
    if isinstance(inline, Link):
        return inline.value or inline.href
    if isinstance(inline, Mention):
        return f"@{inline.display_name or inline.account_id}"
    if isinstance(inline, HardBreak):
        return "\n"
    return inline.value


def _inlines_text(content: tuple[Inline, ...]) -> str:
    return "".join(inline_text(inline) for inline in content)


def _text_lines(block: Block) -> Iterator[str]:
    """The visible lines of one block."""
    if isinstance(block, (Heading, Paragraph)):
        yield from _inlines_text(block.content).splitlines()
    elif isinstance(block, CodeBlock):
        yield from block.text.rstrip().splitlines()
    elif isinstance(block, (BulletList, OrderedList)):
        for item in block.items:
            for part in item.content:
                yield from _text_lines(part)
    elif isinstance(block, Table):
        for row in (block.header, *block.rows):
            yield from (_inlines_text(cell) for cell in row if cell)
    elif isinstance(block, Image) and block.alt:
        yield block.alt
    elif isinstance(block, Rule):
        yield "---"


def _all_inlines(blocks: tuple[Block, ...]) -> Iterator[Inline]:
    """Every inline in *blocks*, nested lists and table cells included."""
    for block in blocks:
        if isinstance(block, (Heading, Paragraph)):
            yield from block.content
        elif isinstance(block, (BulletList, OrderedList)):
            for item in block.items:
                yield from _all_inlines(item.content)
        elif isinstance(block, Table):
            for row in (block.header, *block.rows):
                for cell in row:
                    yield from cell

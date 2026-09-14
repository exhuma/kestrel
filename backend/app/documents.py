"""Source-neutral documents and pure renderers for task-source content."""

from __future__ import annotations

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
class Code:
    """Inline text rendered as code and intended for direct copying."""

    value: str


Inline: TypeAlias = Text | Strong | Code
_MAX_HEADING_LEVEL = 6


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
class BulletList:
    """A flat sequence of paragraph list items."""

    items: tuple[Paragraph, ...]


@dataclass(frozen=True)
class OrderedList:
    """A flat sequence of paragraph list items with ordinal presentation."""

    items: tuple[Paragraph, ...]


@dataclass(frozen=True)
class Rule:
    """A thematic break between document sections."""


@dataclass(frozen=True)
class LegacyMarkdown:
    """Historic text retained verbatim until its producer adopts documents."""

    value: str


Block: TypeAlias = (
    Heading | Paragraph | BulletList | OrderedList | Rule | LegacyMarkdown
)


@dataclass(frozen=True)
class Document:
    """An immutable ordered collection of source-neutral content blocks."""

    blocks: tuple[Block, ...]


def document(*blocks: Block) -> Document:
    """Build and validate a document from the supplied content blocks."""
    for block in blocks:
        _validate_block(block)
    return Document(blocks)


def paragraph(*content: Inline) -> Paragraph:
    """Build a nonempty paragraph from explicitly typed inline content."""
    _validate_inlines(content)
    return Paragraph(content)


def render_markdown(value: Document) -> str:
    """Render a canonical document as Markdown for text-native task sources."""
    return "\n\n".join(_markdown_block(block) for block in value.blocks)


def render_text(value: Document) -> str:
    """Render visible document text for diagnostics and plain-text consumers."""
    return "\n".join(_text_block(block) for block in value.blocks)


def render_adf(value: Document) -> dict[str, object]:
    """Render a canonical document directly as a Jira Cloud ADF document."""
    return {
        "version": 1,
        "type": "doc",
        "content": [_adf_block(block) for block in value.blocks],
    }


def as_document(value: Document | str) -> Document:
    """Return a document, carrying a historic string as an explicit block."""
    if isinstance(value, Document):
        return value
    return document(LegacyMarkdown(value))


def _validate_block(block: Block) -> None:
    """Reject blocks that cannot be represented by every supported renderer."""
    if isinstance(block, Heading) and not _heading_level_is_valid(block):
        raise ValueError("heading level must be between 1 and 6")
    if isinstance(block, (Heading, Paragraph)):
        _validate_inlines(block.content)
    if isinstance(block, LegacyMarkdown) and not block.value:
        raise ValueError("historic text must be nonempty")
    if isinstance(block, (BulletList, OrderedList)) and not block.items:
        raise ValueError("lists require at least one item")


def _heading_level_is_valid(heading: Heading) -> bool:
    """Return whether a heading level is supported by all document renderers."""
    return 1 <= heading.level <= _MAX_HEADING_LEVEL


def _validate_inlines(content: tuple[Inline, ...]) -> None:
    """Reject empty inline sequences and values before rendering starts."""
    if not content or any(not inline.value for inline in content):
        raise ValueError("text content must be nonempty")


def _markdown_block(block: Block) -> str:
    """Render one block as controlled Markdown without parsing any text."""
    if isinstance(block, Heading):
        return f"{'#' * block.level} {_markdown_inlines(block.content)}"
    if isinstance(block, Paragraph):
        return _markdown_inlines(block.content)
    if isinstance(block, LegacyMarkdown):
        return block.value
    if isinstance(block, Rule):
        return "---"
    prefix = "-" if isinstance(block, BulletList) else "1."
    return "\n".join(_markdown_list_item(prefix, item) for item in block.items)


def _markdown_list_item(prefix: str, item: Paragraph) -> str:
    """Render one explicit list item as controlled Markdown."""
    return f"{prefix} {_markdown_inlines(item.content)}"


def _markdown_inlines(content: tuple[Inline, ...]) -> str:
    """Render a flat inline sequence as controlled Markdown."""
    return "".join(
        inline.value
        if isinstance(inline, Text)
        else f"**{inline.value}**"
        if isinstance(inline, Strong)
        else f"`{inline.value}`"
        for inline in content
    )


def _text_block(block: Block) -> str:
    """Render one block's visible content without presentation marks."""
    if isinstance(block, Rule):
        return "---"
    if isinstance(block, (Heading, Paragraph)):
        return "".join(inline.value for inline in block.content)
    if isinstance(block, LegacyMarkdown):
        return block.value
    return "\n".join(_text_list_item(item) for item in block.items)


def _text_list_item(item: Paragraph) -> str:
    """Return the visible text in one list item."""
    return "".join(inline.value for inline in item.content)


def _adf_block(block: Block) -> dict[str, object]:
    """Render one canonical block as a valid ADF top-level node."""
    if isinstance(block, Heading):
        return _adf_text_block("heading", block.content, {"level": block.level})
    if isinstance(block, Paragraph):
        return _adf_text_block("paragraph", block.content)
    if isinstance(block, Rule):
        return {"type": "rule"}
    if isinstance(block, LegacyMarkdown):
        return _adf_text_block("paragraph", (Text(block.value),))
    kind = "bulletList" if isinstance(block, BulletList) else "orderedList"
    return {
        "type": kind,
        "content": [_adf_list_item(item) for item in block.items],
    }


def _adf_list_item(item: Paragraph) -> dict[str, object]:
    """Render one flat paragraph item in the ADF list structure."""
    return {
        "type": "listItem",
        "content": [_adf_text_block("paragraph", item.content)],
    }


def _adf_text_block(
    kind: str, content: tuple[Inline, ...], attrs: dict[str, int] | None = None
) -> dict[str, object]:
    """Render a heading or paragraph with optional node attributes."""
    node: dict[str, object] = {
        "type": kind,
        "content": [_adf_inline(inline) for inline in content],
    }
    if attrs:
        node["attrs"] = attrs
    return node


def _adf_inline(inline: Inline) -> dict[str, object]:
    """Render one explicit inline value as an ADF text node and mark."""
    node: dict[str, object] = {"type": "text", "text": inline.value}
    mark = _adf_mark(inline)
    if mark:
        node["marks"] = [{"type": mark}]
    return node


def _adf_mark(inline: Inline) -> str:
    """Return the ADF mark corresponding to one explicit inline value."""
    if isinstance(inline, Strong):
        return "strong"
    if isinstance(inline, Code):
        return "code"
    return ""

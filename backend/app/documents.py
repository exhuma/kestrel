"""Source-neutral documents and pure renderers for task-source content.

The document model is a small, closed set of inline and block constructs.
``parse_markdown`` turns arbitrary Markdown (including LLM-authored free-form
content) into that model via ``markdown-it-py``; the three renderers then map
the model back onto each platform's native format (Markdown, plain text, or
Jira ADF). Core code builds documents from explicit constructs and never
emits raw Markdown syntax itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias

from app.documents_parser import parse_markdown_blocks


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
    """A hyperlink wrapping inline text, carrying its target URL."""

    href: str
    value: str = ""


Inline: TypeAlias = Text | Strong | Emphasis | Code | Link
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
class CodeBlock:
    """A fenced code block with an optional language tag."""

    language: str = ""
    text: str = ""


@dataclass(frozen=True)
class ListItem:
    """A single list item holding one or more paragraphs."""

    content: tuple[Paragraph, ...]


@dataclass(frozen=True)
class BulletList:
    """A flat sequence of list items."""

    items: tuple[ListItem, ...]


@dataclass(frozen=True)
class OrderedList:
    """A flat sequence of list items with ordinal presentation."""

    start: int = 1
    items: tuple[ListItem, ...] = ()


@dataclass(frozen=True)
class Rule:
    """A thematic break between document sections."""


Block: TypeAlias = (
    Heading | Paragraph | CodeBlock | BulletList | OrderedList | Rule
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


def parse_markdown(text: str) -> Document:
    """Parse a Markdown string into a canonical document.

    Uses ``markdown-it-py`` (CommonMark reference implementation) to convert
    arbitrary Markdown — including LLM-authored free-form content — into the
    closed construct set defined in this module. The result is renderable by
    every supported renderer without loss of structure.

    :param text: A Markdown string; may be empty, yielding an empty document.
    :returns: A ``Document`` whose blocks mirror the parsed structure.
    """
    blocks = tuple(_block_from_dict(d) for d in parse_markdown_blocks(text))
    return Document(blocks)


def _inlines_from_dicts(raw: list[dict[str, str]]) -> tuple[Inline, ...]:
    """Convert raw inline dicts from the parser into Inline constructs."""
    result: list[Inline] = []
    for item in raw:
        kind = item["kind"]
        if kind == "text":
            result.append(Text(value=item["text"]))
        elif kind == "strong":
            result.append(Strong(value=item["text"]))
        elif kind == "emphasis":
            result.append(Emphasis(value=item["text"]))
        elif kind == "code":
            result.append(Code(value=item["text"]))
        elif kind == "link":
            result.append(Link(href=item["href"], value=item["text"]))
    return tuple(result)


def _simple_block(d: dict[str, Any]) -> Block | None:
    """Convert a non-list block dict; returns None for list types."""
    btype = str(d["type"])
    if btype == "heading":
        return Heading(int(d["level"]), _inlines_from_dicts(d["inlines"]))
    if btype == "paragraph":
        return Paragraph(_inlines_from_dicts(d["inlines"]))
    if btype == "code_block":
        return CodeBlock(language=str(d["language"]), text=str(d["text"]))
    if btype == "rule":
        return Rule()
    return None


def _block_from_dict(
    d: dict[str, Any],
) -> Block:
    """Convert one raw block dict from the parser into a Block construct."""
    simple = _simple_block(d)
    if simple is not None:
        return simple
    items = [
        ListItem(tuple(
            Paragraph(_inlines_from_dicts(p["inlines"]))
            for p in item["paragraphs"]
        ))
        for item in d["items"]
    ]
    if str(d["type"]) == "bullet_list":
        return BulletList(items=tuple(items))
    return OrderedList(start=int(d["start"]), items=tuple(items))


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
    """Return a document, parsing a string into its canonical blocks."""
    if isinstance(value, Document):
        return value
    return parse_markdown(value)


def _validate_block(block: Block) -> None:
    """Reject blocks that cannot be represented by every supported renderer."""
    if isinstance(block, Heading) and not _heading_level_is_valid(block):
        raise ValueError("heading level must be between 1 and 6")
    if isinstance(block, (Heading, Paragraph)):
        _validate_inlines(block.content)
    if isinstance(block, (BulletList, OrderedList)):
        if not block.items:
            raise ValueError("lists require at least one item")
        for item in block.items:
            if not item.content:
                raise ValueError("list items require content")


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
    if isinstance(block, (CodeBlock, Rule)):
        return _markdown_atomic_block(block)
    if isinstance(block, BulletList):
        return "\n".join(
            _markdown_list_item("-", item) for item in block.items
        )
    start = block.start
    return "\n".join(
        _markdown_list_item(f"{start + offset}.", item)
        for offset, item in enumerate(block.items)
    )


def _markdown_atomic_block(block: CodeBlock | Rule) -> str:
    """Render a code block or horizontal rule as Markdown."""
    if isinstance(block, CodeBlock):
        fence = "```"
        lang = block.language or ""
        return f"{fence}{lang}\n{block.text.rstrip()}\n{fence}"
    return "---"


def _markdown_list_item(prefix: str, item: ListItem) -> str:
    """Render one explicit list item as controlled Markdown."""
    first = f"{prefix} {_markdown_inlines(item.content[0].content)}"
    rest = [
        f"\n\n{_markdown_inlines(p.content)}"
        for p in item.content[1:]
    ]
    return first + "".join(rest)


def _markdown_inlines(content: tuple[Inline, ...]) -> str:
    """Render a flat inline sequence as controlled Markdown."""
    parts: list[str] = []
    for inline in content:
        if isinstance(inline, Text):
            parts.append(inline.value)
        elif isinstance(inline, Strong):
            parts.append(f"**{inline.value}**")
        elif isinstance(inline, Emphasis):
            parts.append(f"*{inline.value}*")
        elif isinstance(inline, Code):
            parts.append(f"`{inline.value}`")
        elif isinstance(inline, Link):
            text = inline.value or inline.href
            parts.append(f"[{text}]({inline.href})")
    return "".join(parts)


def _text_block(block: Block) -> str:
    """Render one block's visible content without presentation marks."""
    if isinstance(block, Rule):
        return "---"
    if isinstance(block, CodeBlock):
        return block.text.rstrip()
    if isinstance(block, (Heading, Paragraph)):
        return "".join(inline.value for inline in block.content)
    return "\n".join(_text_list_item(item) for item in block.items)


def _text_list_item(item: ListItem) -> str:
    """Return the visible text in one list item."""
    return " ".join(
        "".join(inline.value for inline in p.content)
        for p in item.content
    )


def _adf_block(block: Block) -> dict[str, object]:
    """Render one canonical block as a valid ADF top-level node."""
    if isinstance(block, Heading):
        return _adf_text_block("heading", block.content, {"level": block.level})
    if isinstance(block, Paragraph):
        return _adf_text_block("paragraph", block.content)
    if isinstance(block, CodeBlock):
        return {
            "type": "codeBlock",
            "attrs": {"language": block.language or None},
            "content": [{"type": "text", "text": block.text.rstrip()}],
        }
    if isinstance(block, Rule):
        return {"type": "rule"}
    kind = "bulletList" if isinstance(block, BulletList) else "orderedList"
    return {
        "type": kind,
        "content": [_adf_list_item(item) for item in block.items],
    }


def _adf_list_item(item: ListItem) -> dict[str, object]:
    """Render one list item (one or more paragraphs) in ADF structure."""
    return {
        "type": "listItem",
        "content": [
            _adf_text_block("paragraph", p.content) for p in item.content
        ],
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
    if isinstance(inline, Link):
        text = inline.value or inline.href
        return {
            "type": "text",
            "text": text,
            "marks": [{"type": "link", "attrs": {"href": inline.href}}],
        }
    node: dict[str, object] = {"type": "text", "text": inline.value}
    mark = _adf_mark(inline)
    if mark:
        node["marks"] = [{"type": mark}]
    return node


def _adf_mark(inline: Inline) -> str:
    """Return the ADF mark corresponding to one explicit inline value."""
    if isinstance(inline, Strong):
        return "strong"
    if isinstance(inline, Emphasis):
        return "em"
    if isinstance(inline, Code):
        return "code"
    return ""

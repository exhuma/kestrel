""":class:`~app.documents.Document` → Jira ADF (contracts/adf-mapping.md).

Total over the closed set. An image becomes a link to it (external images
would need a media upload); a marker becomes a paragraph holding
``[kestrel:NAME]`` as code, because Jira Cloud drops HTML comments.
"""

from __future__ import annotations

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
)

Node = dict[str, object]

_MARKS = {Strong: "strong", Emphasis: "em", Code: "code"}


def render_adf(value: Document) -> Node:
    """Render a document as an ADF ``doc`` node."""
    return {
        "version": 1,
        "type": "doc",
        "content": [_block(block) for block in value.blocks],
    }


def marker_text(name: str) -> str:
    """How a marker reads inside its code-marked paragraph."""
    return f"[kestrel:{name}]"


def _block(block: Block) -> Node:
    if isinstance(block, Heading):
        return {"type": "heading", "attrs": {"level": block.level},
                "content": _inlines(block.content)}
    if isinstance(block, Paragraph):
        return _paragraph(block.content)
    if isinstance(block, (BulletList, OrderedList)):
        return _list(block)
    if isinstance(block, Table):
        return _table(block)
    return _leaf(block)


def _leaf(block: CodeBlock | Image | Rule | Marker) -> Node:
    if isinstance(block, CodeBlock):
        return {"type": "codeBlock",
                "attrs": {"language": block.language or None},
                "content": [{"type": "text", "text": block.text.rstrip()}]}
    if isinstance(block, Image):
        return _paragraph((Link(block.src, block.alt),))
    if isinstance(block, Marker):
        return _paragraph((Code(marker_text(block.name)),))
    return {"type": "rule"}


def _paragraph(content: tuple[Inline, ...]) -> Node:
    return {"type": "paragraph", "content": _inlines(content)}


def _list(block: BulletList | OrderedList) -> Node:
    node: Node = {
        "type": "bulletList" if isinstance(block, BulletList)
        else "orderedList",
        "content": [_item(item) for item in block.items],
    }
    if isinstance(block, OrderedList):
        node["attrs"] = {"order": block.start}
    return node


def _item(item: ListItem) -> Node:
    return {"type": "listItem", "content": [
        _paragraph(part.content) if isinstance(part, Paragraph)
        else _list(part)
        for part in item.content
    ]}


def _table(block: Table) -> Node:
    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": [
            _row("tableHeader", block.header),
            *(_row("tableCell", row) for row in block.rows),
        ],
    }


def _row(kind: str, cells: tuple[Cell, ...]) -> Node:
    return {"type": "tableRow", "content": [
        {"type": kind, "attrs": {}, "content": [_paragraph(cell)]}
        for cell in cells
    ]}


def _inlines(content: tuple[Inline, ...]) -> list[Node]:
    return [_inline(inline) for inline in content]


def _inline(inline: Inline) -> Node:
    if isinstance(inline, Mention):
        name = inline.display_name or inline.account_id
        return {"type": "mention",
                "attrs": {"id": inline.account_id, "text": f"@{name}"}}
    if isinstance(inline, HardBreak):
        return {"type": "hardBreak"}
    if isinstance(inline, Link):
        return {"type": "text", "text": inline.value or inline.href,
                "marks": [{"type": "link", "attrs": {"href": inline.href}}]}
    node: Node = {"type": "text", "text": inline.value}
    mark = _MARKS.get(type(inline))
    if mark:
        node["marks"] = [{"type": mark}]
    return node

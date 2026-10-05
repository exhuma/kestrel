""":class:`~app.documents.Document` → Markdown.

The output parses back to the same document (``markdown_in``). A marker
renders as an HTML comment, invisible on GitHub and GitLab; a mention as
``@name``, which is a native mention where the name is a login.
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
    Text,
)


def render_markdown(value: Document) -> str:
    """Render a document as Markdown."""
    return "\n\n".join(_block(block) for block in value.blocks)


def _block(block: Block) -> str:
    if isinstance(block, Heading):
        return f"{'#' * block.level} {_inlines(block.content)}"
    if isinstance(block, Paragraph):
        return _inlines(block.content)
    if isinstance(block, (BulletList, OrderedList)):
        return "\n".join(_list(block))
    if isinstance(block, Table):
        return _table(block)
    return _leaf(block)


def _leaf(block: CodeBlock | Image | Rule | Marker) -> str:
    if isinstance(block, CodeBlock):
        return f"```{block.language}\n{block.text.rstrip()}\n```"
    if isinstance(block, Image):
        return f"![{block.alt}]({block.src})"
    if isinstance(block, Marker):
        return f"<!-- kestrel:{block.name} -->"
    return "---"


def _list(block: BulletList | OrderedList) -> list[str]:
    """The lines of a list; nested content is indented under its item."""
    lines: list[str] = []
    for offset, item in enumerate(block.items):
        prefix = (
            "-" if isinstance(block, BulletList)
            else f"{block.start + offset}."
        )
        lines += _item(prefix, item)
    return lines


def _item(prefix: str, item: ListItem) -> list[str]:
    indent = " " * (len(prefix) + 1)
    loose = sum(isinstance(p, Paragraph) for p in item.content) > 1
    lines: list[str] = []
    for index, part in enumerate(item.content):
        rendered = (
            _inlines(part.content).split("\n")
            if isinstance(part, Paragraph) else _list(part)
        )
        if index and loose and isinstance(part, Paragraph):
            lines.append("")
        lines += rendered
    first, *rest = lines or [""]
    return [f"{prefix} {first}", *(f"{indent}{line}" if line else ""
                                   for line in rest)]


def _table(block: Table) -> str:
    rows = [
        _row(block.header),
        "| " + " | ".join("---" for _ in block.header) + " |",
        *(_row(row) for row in block.rows),
    ]
    return "\n".join(rows)


def _row(cells: tuple[Cell, ...]) -> str:
    return "| " + " | ".join(
        _inlines(cell).replace("|", "\\|").replace("\n", " ")
        for cell in cells
    ) + " |"


def _inlines(content: tuple[Inline, ...]) -> str:
    return "".join(_inline(inline) for inline in content)


def _inline(inline: Inline) -> str:
    if isinstance(inline, Text):
        return inline.value
    if isinstance(inline, (Strong, Emphasis, Code)):
        return _marked(inline)
    if isinstance(inline, Link):
        return f"[{inline.value or inline.href}]({inline.href})"
    if isinstance(inline, Mention):
        return f"@{inline.display_name or inline.account_id}"
    return "\\\n" if isinstance(inline, HardBreak) else ""


def _marked(inline: Strong | Emphasis | Code) -> str:
    if isinstance(inline, Strong):
        return f"**{inline.value}**"
    if isinstance(inline, Emphasis):
        return f"*{inline.value}*"
    fence = "``" if "`" in inline.value else "`"
    return f"{fence}{inline.value}{fence}"

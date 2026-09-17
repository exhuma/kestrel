"""Round-trip and parser tests for app.documents."""
from __future__ import annotations

import pytest

from app.documents import (
    BulletList,
    Code,
    CodeBlock,
    Document,
    Emphasis,
    Heading,
    Link,
    ListItem,
    OrderedList,
    Paragraph,
    Rule,
    Strong,
    Text,
    as_document,
    document,
    paragraph,
    parse_markdown,
    render_adf,
    render_markdown,
    render_text,
)

HEADING_LEVEL_TWO = 2
HEADING_LEVEL_THREE = 3
TWO_ITEMS = 2
THREE_ITEMS = 3


def test_parse_empty_string_yields_empty_document() -> None:
    doc = parse_markdown("")
    assert doc.blocks == ()


def test_parse_single_paragraph() -> None:
    doc = parse_markdown("Hello world")
    assert len(doc.blocks) == 1
    assert isinstance(doc.blocks[0], Paragraph)
    assert doc.blocks[0].content == (Text("Hello world"),)


def test_parse_heading_levels() -> None:
    for level in range(1, 7):
        doc = parse_markdown(f"{'#' * level} Title")
        h = doc.blocks[0]
        assert isinstance(h, Heading)
        assert h.level == level
        assert h.content == (Text("Title"),)


def test_parse_strong_and_emphasis() -> None:
    doc = parse_markdown("**bold** and *italic*")
    p = doc.blocks[0]
    assert isinstance(p, Paragraph)
    assert p.content == (Strong("bold"), Text(" and "), Emphasis("italic"))


def test_parse_inline_code() -> None:
    doc = parse_markdown("Use `foo()` here")
    p = doc.blocks[0]
    assert isinstance(p, Paragraph)
    assert p.content == (Text("Use "), Code("foo()"), Text(" here"))


def test_parse_link() -> None:
    doc = parse_markdown("[text](https://example.com)")
    p = doc.blocks[0]
    assert isinstance(p, Paragraph)
    assert p.content == (Link(href="https://example.com", value="text"),)


def test_parse_bullet_list_single_item() -> None:
    doc = parse_markdown("- item one")
    bl = doc.blocks[0]
    assert isinstance(bl, BulletList)
    assert len(bl.items) == 1
    assert bl.items[0].content == (Paragraph((Text("item one"),)),)


def test_parse_bullet_list_multiple_items() -> None:
    doc = parse_markdown("- a\n- b\n- c")
    bl = doc.blocks[0]
    assert isinstance(bl, BulletList)
    assert len(bl.items) == THREE_ITEMS
    assert bl.items[1].content == (Paragraph((Text("b"),)),)


def test_parse_ordered_list() -> None:
    doc = parse_markdown("1. first\n2. second")
    ol = doc.blocks[0]
    assert isinstance(ol, OrderedList)
    assert ol.start == 1
    assert len(ol.items) == TWO_ITEMS
    assert ol.items[0].content == (Paragraph((Text("first"),)),)


def test_parse_ordered_list_custom_start() -> None:
    doc = parse_markdown("3. third\n4. fourth")
    ol = doc.blocks[0]
    assert isinstance(ol, OrderedList)
    assert ol.start == HEADING_LEVEL_THREE
    assert len(ol.items) == TWO_ITEMS


def test_parse_loose_ordered_list_with_bodies() -> None:
    text = "1. **Title**\n\n   Body text.\n\n2. **Second**\n\n   More body."
    doc = parse_markdown(text)
    ol = doc.blocks[0]
    assert isinstance(ol, OrderedList)
    assert len(ol.items) == TWO_ITEMS
    item1 = ol.items[0].content
    assert len(item1) == TWO_ITEMS
    assert item1[0].content == (Strong("Title"),)
    assert item1[1].content == (Text("Body text."),)


def test_parse_fenced_code_block() -> None:
    doc = parse_markdown("```python\nprint('hi')\n```")
    cb = doc.blocks[0]
    assert isinstance(cb, CodeBlock)
    assert cb.language == "python"
    assert cb.text.strip() == "print('hi')"


def test_parse_rule() -> None:
    doc = parse_markdown("---")
    assert len(doc.blocks) == 1
    assert isinstance(doc.blocks[0], Rule)


def test_parse_multiple_blocks() -> None:
    text = "# Head\n\nPara one.\n\n- item\n\n## Sub"
    doc = parse_markdown(text)
    types = [type(b).__name__ for b in doc.blocks]
    assert types == ["Heading", "Paragraph", "BulletList", "Heading"]


def test_round_trip_markdown() -> None:
    text = "# Title\n\nSome **bold** and `code`.\n\n- a\n- b"
    doc = parse_markdown(text)
    out = render_markdown(doc)
    assert "# Title" in out
    assert "**bold**" in out
    assert "`code`" in out
    assert "- a" in out
    assert "- b" in out


def test_round_trip_preserves_structure() -> None:
    text = (
        "1. **Add endpoint**\n\n   Expose GET /widgets."
        "\n\n2. **Add UI**\n\n   Render list."
    )
    doc = parse_markdown(text)
    out = render_markdown(doc)
    assert "1. **Add endpoint**" in out
    assert "Expose GET /widgets." in out
    assert "2. **Add UI**" in out
    assert "Render list." in out


def test_render_text_strips_formatting() -> None:
    doc = document(
        Heading(1, (Text("Title"),)),
        paragraph(Strong("bold"), Text(" and "), Emphasis("italic")),
    )
    text = render_text(doc)
    assert "Title" in text
    assert "bold and italic" in text
    assert "**" not in text


def test_render_adf_structure() -> None:
    doc = document(
        Heading(2, (Text("Review"),)),
        paragraph(Text("Approve with "), Strong("token")),
    )
    adf = render_adf(doc)
    assert adf["type"] == "doc"
    assert adf["version"] == 1
    blocks: list[dict[str, object]] = adf["content"]  # type: ignore[assignment]
    assert blocks[0]["type"] == "heading"
    attrs: dict[str, object] = blocks[0]["attrs"]  # type: ignore[assignment]
    assert attrs["level"] == HEADING_LEVEL_TWO
    assert blocks[1]["type"] == "paragraph"


def test_as_document_passthrough() -> None:
    doc = document(paragraph(Text("hi")))
    assert as_document(doc) is doc


def test_as_document_parses_string() -> None:
    result = as_document("**bold**")
    assert isinstance(result, Document)
    assert len(result.blocks) == 1


def test_document_validation_rejects_empty_paragraph() -> None:
    with pytest.raises(ValueError):
        document(Paragraph(()))


def test_document_validation_rejects_empty_list_item() -> None:
    with pytest.raises(ValueError):
        document(BulletList((ListItem(()),)))

"""Markdown in and out of the document model (Principle VI adapter)."""
from __future__ import annotations

import pytest

from app.document_formats.markdown import parse_markdown, render_markdown
from app.documents import (
    BulletList,
    Code,
    CodeBlock,
    Emphasis,
    HardBreak,
    Heading,
    Image,
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
    document,
    paragraph,
)

THIRD = 3


def _item(*inlines) -> ListItem:
    return ListItem((paragraph(*inlines),))


def test_empty_text_is_an_empty_document() -> None:
    assert parse_markdown("").blocks == ()


@pytest.mark.parametrize("level", range(1, 7))
def test_headings(level: int) -> None:
    assert parse_markdown(f"{'#' * level} Title").blocks == (
        Heading(level, (Text("Title"),)),
    )


def test_marks_code_and_links() -> None:
    doc = parse_markdown("**b** and *i*, `c()` [t](https://x)")

    assert doc.blocks == (paragraph(
        Strong("b"), Text(" and "), Emphasis("i"), Text(", "), Code("c()"),
        Text(" "), Link("https://x", "t"),
    ),)


def test_a_soft_break_is_a_space_and_a_hard_break_is_kept() -> None:
    assert parse_markdown("a\nb").blocks == (paragraph(Text("a b")),)
    assert parse_markdown("a\\\nb").blocks == (
        paragraph(Text("a"), HardBreak(), Text("b")),
    )


def test_nested_marks_keep_the_outer_one() -> None:
    """Ensure ``***x***`` (emphasis around strong) keeps the emphasis."""
    assert parse_markdown("***both***").blocks == (paragraph(Emphasis("both")),)


def test_lists_ordered_with_start_and_loose_bodies() -> None:
    doc = parse_markdown("3. **T**\n\n   Body.\n\n4. two")

    ol = doc.blocks[0]
    assert isinstance(ol, OrderedList)
    assert ol.start == THIRD
    assert ol.items[0].content == (
        paragraph(Strong("T")), paragraph(Text("Body.")),
    )


def test_nested_lists_stay_inside_their_item() -> None:
    doc = parse_markdown("- a\n  - b\n  - c\n- d")

    assert doc.blocks == (BulletList((
        ListItem((
            paragraph(Text("a")),
            BulletList((_item(Text("b")), _item(Text("c")))),
        )),
        _item(Text("d")),
    )),)


def test_tables() -> None:
    doc = parse_markdown(
        "| Task | Size |\n|---|---|\n| Add **API** | S |\n| UI | |"
    )

    assert doc.blocks == (Table(
        ((Text("Task"),), (Text("Size"),)),
        (
            ((Text("Add "), Strong("API")), (Text("S"),)),
            ((Text("UI"),), ()),
        ),
    ),)


def test_an_image_becomes_its_own_block() -> None:
    doc = parse_markdown("Before ![shot](https://x/s.png) after")

    assert doc.blocks == (
        paragraph(Text("Before ")),
        Image("https://x/s.png", "shot"),
        paragraph(Text(" after")),
    )


def test_code_block_rule_and_blockquote() -> None:
    doc = parse_markdown("```python\nprint(1)\n```\n\n---\n\n> quoted")

    assert doc.blocks == (
        CodeBlock("python", "print(1)\n"), Rule(), paragraph(Text("quoted")),
    )


def test_a_kestrel_marker_comment_is_a_marker() -> None:
    assert parse_markdown("Hi\n\n<!-- kestrel:posted -->").blocks == (
        paragraph(Text("Hi")), Marker("posted"),
    )


def test_other_html_keeps_only_its_text() -> None:
    assert parse_markdown("<UNDERSTANDING>Ok</UNDERSTANDING>").blocks == (
        paragraph(Text("Ok")),
    )


def test_parsed_documents_are_valid() -> None:
    """Ensure the parser never builds an invalid document."""
    doc = parse_markdown("- \n\n|a|\n|-|\n||\n\n****\n\n[](https://x)")

    assert document(*doc.blocks) == doc


def test_render_every_construct() -> None:
    doc = document(
        Heading(2, (Text("T"),)),
        paragraph(Strong("b"), Text(" "), Emphasis("i"), Text(" "),
                  Code("c"), Text(" "), Link("https://x", "l"), HardBreak(),
                  Mention("acc", "jane")),
        OrderedList(2, (ListItem((
            paragraph(Text("one")),
            BulletList((_item(Text("nested")),)),
        )),)),
        Table(((Text("a"),), (Text("b|c"),)), (((Text("1"),), ()),)),
        Image("https://x/s.png", "shot"),
        CodeBlock("sh", "ls\n"),
        Rule(),
        Marker("posted"),
    )

    assert render_markdown(doc) == (
        "## T\n\n"
        "**b** *i* `c` [l](https://x)\\\n@jane\n\n"
        "2. one\n   - nested\n\n"
        "| a | b\\|c |\n| --- | --- |\n| 1 |  |\n\n"
        "![shot](https://x/s.png)\n\n"
        "```sh\nls\n```\n\n"
        "---\n\n"
        "<!-- kestrel:posted -->"
    )


ROUND_TRIP = [
    document(paragraph(Text("plain"))),
    document(Heading(3, (Text("h "), Code("x")),)),
    document(paragraph(Text("a"), HardBreak(), Text("b"))),
    document(BulletList((
        ListItem((paragraph(Text("a")), OrderedList(1, (_item(Text("b")),)))),
    ))),
    document(OrderedList(5, (_item(Strong("x")), _item(Text("y"))))),
    document(Table(((Text("h"),), (Text("k"),)), (((Text("v"),), ()),))),
    document(Image("https://x/i.png", "i"), Rule(), Marker("refined")),
    document(CodeBlock("", "raw\n")),
]


@pytest.mark.parametrize("doc", ROUND_TRIP)
def test_parse_inverts_render(doc) -> None:
    assert parse_markdown(render_markdown(doc)) == doc


def test_a_mention_renders_as_an_at_name() -> None:
    assert render_markdown(document(paragraph(Mention("1", "octo")))) == (
        "@octo"
    )


def test_a_paragraph_with_only_an_image_is_not_empty() -> None:
    assert parse_markdown("![a](https://x)").blocks == (
        Image("https://x", "a"),
    )


def test_a_list_item_with_a_code_block_keeps_its_text() -> None:
    doc = parse_markdown("- step\n\n  ```\n  run it\n  ```")

    item = doc.blocks[0].items[0]
    assert item.content == (
        paragraph(Text("step")), Paragraph((Code("run it"),)),
    )

"""The document model: constructs, validation and derived queries.

Parsing and rendering live in ``app.document_formats`` (constitution
Principle VI) and are tested in ``test_document_formats_*``.
"""
from __future__ import annotations

import pytest

from app.documents import (
    BulletList,
    Code,
    CodeBlock,
    Document,
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
    validate_document,
)

#: One block per construct kind in the closed set.
EVERY_BLOCK_KIND = 8


def _item(*inlines) -> ListItem:
    return ListItem((paragraph(*inlines),))


def test_a_document_holds_every_construct() -> None:
    """Ensure each construct of the closed set validates in a document."""
    doc = document(
        Heading(2, (Text("Title"),)),
        paragraph(
            Text("Hi "), Mention("acc-1", "Jane"), HardBreak(),
            Strong("b"), Emphasis("i"), Code("c"), Link("https://x", "x"),
        ),
        CodeBlock("python", "print(1)"),
        BulletList((
            ListItem((
                paragraph(Text("outer")),
                OrderedList(2, (_item(Text("inner")),)),
            )),
        )),
        Image("https://x/shot.png", "shot"),
        Table(((Text("a"),), (Text("b"),)), (((Text("1"),), ()),)),
        Rule(),
        Marker("posted"),
    )

    assert len(doc.blocks) == EVERY_BLOCK_KIND


@pytest.mark.parametrize(
    "block",
    [
        Paragraph(()),
        Paragraph((Text(""),)),
        Heading(7, (Text("x"),)),
        BulletList(()),
        BulletList((ListItem(()),)),
        Table((), ()),
        Table(((Text("a"),),), (((Text("1"),), (Text("2"),)),)),
        Image("", "alt"),
        Marker("Not A Name"),
        Paragraph((Mention("", "Jane"),)),
        Paragraph((Link("", "text"),)),
    ],
    ids=[
        "empty-paragraph", "empty-text", "heading-level", "empty-list",
        "empty-item", "empty-table", "ragged-table", "image-without-src",
        "bad-marker-name", "mention-without-account", "link-without-href",
    ],
)
def test_invalid_blocks_are_rejected(block) -> None:
    with pytest.raises(ValueError):
        document(block)


def test_a_nested_invalid_item_is_rejected() -> None:
    with pytest.raises(ValueError):
        document(BulletList((ListItem((BulletList(()),)),)))


def test_validate_document_checks_an_existing_document() -> None:
    """Ensure parsers can validate what they built without builders."""
    with pytest.raises(ValueError):
        validate_document(Document((Paragraph(()),)))


def test_a_link_may_omit_its_text() -> None:
    assert document(paragraph(Link("https://x"))).blocks


def test_plain_text_drops_marks_and_markers() -> None:
    doc = document(
        Heading(1, (Text("Title"),)),
        paragraph(Strong("bold"), Text(" and "), Emphasis("italic")),
        paragraph(Mention("acc-1", "Jane"), Text(" see"), HardBreak(),
                  Link("https://x", "this")),
        BulletList((_item(Text("one")), _item(Text("two")))),
        Table(((Text("h"),),), (((Text("c"),),),)),
        Image("https://x/i.png", "picture"),
        Marker("posted"),
    )

    text = doc.plain_text()

    assert text.splitlines() == [
        "Title", "bold and italic", "@Jane see", "this",
        "one", "two", "h", "c", "picture",
    ]


def test_plain_text_of_a_mention_without_a_name_uses_the_account() -> None:
    assert document(paragraph(Mention("acc-9"))).plain_text() == "@acc-9"


def test_markers_lists_the_marker_names() -> None:
    doc = document(paragraph(Text("x")), Marker("posted"), Marker("refined"))

    assert doc.markers() == frozenset({"posted", "refined"})


def test_mentions_are_found_anywhere() -> None:
    doc = document(
        paragraph(Mention("a")),
        Heading(2, (Mention("b"),)),
        BulletList((ListItem((
            paragraph(Text("x")),
            BulletList((_item(Mention("c")),)),
        )),)),
        Table(((Mention("d"),),), (((Mention("e"),),),)),
    )

    assert doc.mentions() == frozenset({"a", "b", "c", "d", "e"})


def test_documents_are_comparable_values() -> None:
    assert document(paragraph(Text("x"))) == document(paragraph(Text("x")))

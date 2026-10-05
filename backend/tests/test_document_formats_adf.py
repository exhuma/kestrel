"""Jira ADF in and out of the document model (contracts/adf-mapping.md)."""
from __future__ import annotations

import pytest

from app.document_formats.adf import parse_adf, render_adf
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


def _item(*inlines) -> ListItem:
    return ListItem((paragraph(*inlines),))


def _doc(*content: dict) -> dict:
    return {"version": 1, "type": "doc", "content": list(content)}


def _text(text: str, *marks: dict) -> dict:
    node: dict = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def _para(*content: dict) -> dict:
    return {"type": "paragraph", "content": list(content)}


def test_inlines_render_as_text_nodes_marks_mentions_and_breaks() -> None:
    adf = render_adf(document(paragraph(
        Text("a"), Strong("b"), Emphasis("c"), Code("d"),
        Link("https://x", "e"), Mention("acc-1", "Jane"), HardBreak(),
    )))

    assert adf == _doc(_para(
        _text("a"),
        _text("b", {"type": "strong"}),
        _text("c", {"type": "em"}),
        _text("d", {"type": "code"}),
        _text("e", {"type": "link", "attrs": {"href": "https://x"}}),
        {"type": "mention", "attrs": {"id": "acc-1", "text": "@Jane"}},
        {"type": "hardBreak"},
    ))


def test_blocks_render_with_their_attributes() -> None:
    adf = render_adf(document(
        Heading(2, (Text("h"),)),
        CodeBlock("python", "x = 1\n"),
        OrderedList(3, (ListItem((
            paragraph(Text("one")),
            BulletList((_item(Text("nested")),)),
        )),)),
        Rule(),
    ))

    assert adf["content"] == [
        {"type": "heading", "attrs": {"level": 2}, "content": [_text("h")]},
        {"type": "codeBlock", "attrs": {"language": "python"},
         "content": [_text("x = 1")]},
        {"type": "orderedList", "attrs": {"order": 3}, "content": [{
            "type": "listItem",
            "content": [
                _para(_text("one")),
                {"type": "bulletList", "content": [{
                    "type": "listItem", "content": [_para(_text("nested"))],
                }]},
            ],
        }]},
        {"type": "rule"},
    ]


def test_a_table_has_header_cells_then_body_cells() -> None:
    adf = render_adf(document(
        Table(((Text("Task"),), (Text("Size"),)), (((Text("API"),), ()),))
    ))

    table = adf["content"][0]
    assert table["type"] == "table"
    header, body = table["content"]
    assert [c["type"] for c in header["content"]] == ["tableHeader"] * 2
    assert [c["type"] for c in body["content"]] == ["tableCell"] * 2
    assert body["content"][1]["content"] == [{"type": "paragraph",
                                              "content": []}]


def test_an_image_renders_as_a_link_and_a_marker_as_code() -> None:
    adf = render_adf(document(
        Image("https://x/s.png", "shot"), Marker("posted"),
    ))

    assert adf["content"] == [
        _para(_text("shot", {"type": "link",
                             "attrs": {"href": "https://x/s.png"}})),
        _para(_text("[kestrel:posted]", {"type": "code"})),
    ]


EVERY_CONSTRUCT = [
    document(paragraph(Text("plain"), Strong("s"), Emphasis("e"),
                       Code("c"), Link("https://x", "l"), HardBreak(),
                       Mention("acc", "Jane"))),
    document(Heading(4, (Text("h"),)), Rule()),
    document(CodeBlock("sh", "ls -la"), CodeBlock("", "plain")),
    document(BulletList((ListItem((
        paragraph(Text("a")),
        OrderedList(2, (_item(Text("b")), _item(Text("c")))),
    )),))),
    document(Table(((Text("h1"),), (Strong("h2"),)),
                   (((Text("v"),), ()), ((), (Code("x"),))))),
    document(paragraph(Text("x")), Marker("posted"), Marker("refined")),
]


@pytest.mark.parametrize("doc", EVERY_CONSTRUCT)
def test_parse_inverts_render(doc) -> None:
    assert parse_adf(render_adf(doc)) == doc


def test_an_image_reads_back_as_a_link() -> None:
    """ADF has no external image node, so an image comes back a link."""
    doc = document(Image("https://x/s.png", "shot"))

    assert parse_adf(render_adf(doc)) == document(
        paragraph(Link("https://x/s.png", "shot"))
    )


def test_containers_keep_their_children() -> None:
    adf = _doc(
        {"type": "panel", "content": [_para(_text("in panel"))]},
        {"type": "expand", "attrs": {"title": "More"},
         "content": [_para(_text("in expand"))]},
        {"type": "blockquote", "content": [_para(_text("quoted"))]},
    )

    assert parse_adf(adf) == document(
        paragraph(Text("in panel")), paragraph(Text("in expand")),
        paragraph(Text("quoted")),
    )


def test_inline_extras_degrade_to_text_or_links() -> None:
    adf = _doc(_para(
        {"type": "emoji", "attrs": {"shortName": ":smile:", "text": "😄"}},
        _text(" "),
        {"type": "inlineCard", "attrs": {"url": "https://x/card"}},
        _text(" "),
        {"type": "status", "attrs": {"text": "DONE"}},
        _text(" u", {"type": "underline"}),
    ))

    assert parse_adf(adf) == document(paragraph(
        Text("😄 "), Link("https://x/card", "https://x/card"),
        Text(" DONE u"),
    ))


def test_external_media_is_an_image_and_attached_media_its_alt() -> None:
    adf = _doc(
        {"type": "mediaSingle", "content": [{"type": "media", "attrs": {
            "type": "external", "url": "https://x/a.png", "alt": "a",
        }}]},
        {"type": "mediaSingle", "content": [{"type": "media", "attrs": {
            "type": "file", "id": "123", "alt": "attached",
        }}]},
        {"type": "mediaSingle", "content": [{"type": "media", "attrs": {
            "type": "file", "id": "456",
        }}]},
    )

    assert parse_adf(adf) == document(
        Image("https://x/a.png", "a"), paragraph(Text("attached")),
    )


def test_a_table_without_header_cells_uses_its_first_row() -> None:
    def cell(text: str) -> dict:
        return {"type": "tableCell", "content": [_para(_text(text))]}

    adf = _doc({"type": "table", "content": [
        {"type": "tableRow", "content": [cell("a"), cell("b")]},
        {"type": "tableRow", "content": [cell("1")]},
    ]})

    assert parse_adf(adf) == document(
        Table(((Text("a"),), (Text("b"),)), (((Text("1"),), ()),))
    )


@pytest.mark.parametrize(
    "value",
    [None, "", "plain string", {"type": "doc"}, {"content": "x"},
     _doc({"type": "unknownNode"}), _doc(_para()), _doc({"type": "rule"})],
    ids=["none", "empty", "string", "no-content", "bad-content", "unknown",
         "empty-paragraph", "rule"],
)
def test_anything_parses_without_raising(value) -> None:
    doc = parse_adf(value)

    assert document(*doc.blocks) == doc


def test_a_plain_string_is_one_paragraph_per_line_block() -> None:
    """Jira Server returns plain text; it is kept as paragraphs."""
    assert parse_adf("first\n\nsecond") == document(
        paragraph(Text("first")), paragraph(Text("second")),
    )


def test_mentions_read_back_with_their_account() -> None:
    adf = _doc(_para(
        {"type": "mention", "attrs": {"id": "acc-7", "text": "@Omar"}},
    ))

    assert parse_adf(adf).mentions() == frozenset({"acc-7"})
    assert parse_adf(adf) == document(paragraph(Mention("acc-7", "Omar")))


def test_a_marker_lookalike_with_other_text_is_just_text() -> None:
    adf = _doc(_para(_text("see [kestrel:posted]", {"type": "code"})))

    assert parse_adf(adf).markers() == frozenset()


def test_an_ordered_list_without_order_starts_at_one() -> None:
    adf = _doc({"type": "orderedList", "content": [
        {"type": "listItem", "content": [_para(_text("x"))]},
    ]})

    assert parse_adf(adf) == document(OrderedList(1, (_item(Text("x")),)))


def test_a_list_item_with_a_code_block_keeps_its_text() -> None:
    adf = _doc({"type": "bulletList", "content": [{
        "type": "listItem", "content": [
            _para(_text("step")),
            {"type": "codeBlock", "content": [_text("run it")]},
        ],
    }]})

    item = parse_adf(adf).blocks[0].items[0]
    assert item.content == (
        paragraph(Text("step")), Paragraph((Code("run it"),)),
    )

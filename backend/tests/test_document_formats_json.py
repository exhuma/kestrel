"""Document JSON, the persistence format (Principle VI boundary)."""
from __future__ import annotations

import json

import pytest

from app.document_formats.document_json import (
    document_json,
    dump_document,
    load_document,
    parse_document_json,
)
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
    Rule,
    Strong,
    Table,
    Text,
    document,
    paragraph,
)

EVERYTHING = document(
    Heading(1, (Text("T"),)),
    paragraph(Text("a"), Strong("b"), Emphasis("c"), Code("d"),
              Link("https://x", "e"), Link("https://y"), HardBreak(),
              Mention("acc", "Jane"), Mention("acc-2")),
    CodeBlock("py", "x"),
    BulletList((ListItem((
        paragraph(Text("o")),
        OrderedList(4, (ListItem((paragraph(Text("i")),)),)),
    )),)),
    Image("https://x/i.png", "i"),
    Table(((Text("h"),), (Text("k"),)), (((Text("v"),), ()),)),
    Rule(),
    Marker("posted"),
)


def test_every_construct_round_trips() -> None:
    assert parse_document_json(document_json(EVERYTHING)) == EVERYTHING


def test_text_round_trip_through_a_string() -> None:
    assert load_document(dump_document(EVERYTHING)) == EVERYTHING


def test_the_payload_is_versioned_json() -> None:
    payload = json.loads(dump_document(document(paragraph(Text("x")))))

    assert payload["version"] == 1
    assert payload["blocks"][0]["type"] == "paragraph"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"version": 2, "blocks": []},
        {"version": 1, "blocks": "x"},
        {"version": 1, "blocks": [{"type": "nope"}]},
        {"version": 1, "blocks": [{"type": "paragraph", "content": [
            {"type": "nope"}]}]},
        {"version": 1, "blocks": [{"type": "paragraph", "content": []}]},
    ],
    ids=["not-object", "version", "blocks-not-list", "unknown-block",
         "unknown-inline", "invalid-document"],
)
def test_malformed_payloads_are_rejected(payload) -> None:
    with pytest.raises(ValueError):
        parse_document_json(payload)


def test_load_rejects_text_that_is_not_json() -> None:
    with pytest.raises(ValueError):
        load_document("# just markdown")

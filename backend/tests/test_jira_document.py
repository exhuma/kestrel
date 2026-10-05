"""Jira Cloud comments and descriptions as Documents (feature 046)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.document_formats.adf import render_adf
from app.documents import (
    BulletList,
    Code,
    Heading,
    ListItem,
    Marker,
    Mention,
    Text,
    document,
    paragraph,
)
from app.ports import Person
from app.services.jira import JiraClient, JiraTaskSource


def _client(handler) -> JiraClient:
    """Build a Cloud Jira client against an in-memory HTTP transport."""
    client = JiraClient("https://jira.example", deployment="cloud")
    client._http = httpx.AsyncClient(
        base_url="https://jira.example/rest/api/3",
        transport=httpx.MockTransport(handler),
    )
    return client


def _recording(seen: dict, response: dict, status: int = 201):
    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["params"] = dict(req.url.params)
        seen["body"] = json.loads(req.content) if req.content else None
        return httpx.Response(status, json=response)
    return handler


@pytest.mark.asyncio
async def test_a_comment_is_the_document_plus_its_marker_as_adf() -> None:
    """Ensure no Markdown round-trip: the ADF is the document, rendered."""
    seen: dict = {}
    body = document(
        Heading(2, (Text("Review"),)),
        BulletList((ListItem((paragraph(Text("Use "), Code("x")),)),)),
        paragraph(Mention("acc-1", "Jane"), Text(" please confirm")),
    )

    source = JiraTaskSource(_client(_recording(seen, {"self": "u"})))
    await source.post_comment("RFC-1", body)

    assert seen["path"] == "/rest/api/3/issue/RFC-1/comment"
    expected = document(*body.blocks, Marker("posted"))
    assert seen["body"]["body"] == render_adf(expected)


@pytest.mark.asyncio
async def test_comment_marking_can_be_disabled() -> None:
    seen: dict = {}
    body = document(paragraph(Text("hi")))

    source = JiraTaskSource(
        _client(_recording(seen, {"self": "u"})),
        comment_sentinel_enabled=False,
    )
    await source.post_comment("RFC-1", body)

    assert seen["body"]["body"] == render_adf(body)


@pytest.mark.asyncio
async def test_a_mention_notifies_by_account() -> None:
    seen: dict = {}
    source = JiraTaskSource(_client(_recording(seen, {"self": "u"})))

    await source.post_comment(
        "RFC-1", document(paragraph(Mention("acc-9", "Omar")))
    )

    first = seen["body"]["body"]["content"][0]["content"][0]
    assert first == {"type": "mention",
                     "attrs": {"id": "acc-9", "text": "@Omar"}}


@pytest.mark.asyncio
async def test_comments_read_back_as_documents_with_accounts() -> None:
    comment = {
        "id": "10042",
        "author": {"accountId": "acc-3", "displayName": "Jane Reporter"},
        "created": "2026-10-05T10:00:00.000+0000",
        "body": {"type": "doc", "version": 1, "content": [{
            "type": "paragraph",
            "content": [{"type": "text", "text": "@kestrel looks right"}],
        }]},
    }
    seen: dict = {}
    handler = _recording(seen, {"comments": [comment], "total": 1}, 200)

    page = await JiraTaskSource(_client(handler)).list_comments("RFC-1")

    (item,) = page.comments
    assert item.external_id == "jira-comment:RFC-1:10042"
    assert item.author == Person("acc-3", "Jane Reporter")
    assert item.body == document(paragraph(Text("@kestrel looks right")))
    assert page.cursor == "2026-10-05T10:00:00.000+0000"


@pytest.mark.asyncio
async def test_kestrels_own_comment_reads_back_with_its_marker() -> None:
    """Ensure the marker survives Jira, so kestrel can skip its own."""
    posted = render_adf(document(paragraph(Text("Hi")), Marker("posted")))
    comment = {"id": "1", "author": {"accountId": "op"},
               "created": "2026-10-05T10:00:00.000+0000", "body": posted}
    handler = _recording({}, {"comments": [comment], "total": 1}, 200)

    page = await JiraTaskSource(_client(handler)).list_comments("RFC-1")

    assert page.comments[0].body.markers() == frozenset({"posted"})


@pytest.mark.asyncio
async def test_an_issue_has_its_reporter_and_change_owner() -> None:
    issue = {"key": "RFC-1", "fields": {
        "summary": "Export",
        "description": {"type": "doc", "version": 1, "content": [{
            "type": "heading", "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Why"}],
        }]},
        "reporter": {"accountId": "acc-r", "displayName": "Rita"},
        "customfield_10051": {"accountId": "acc-o", "displayName": "Owen"},
    }}
    seen: dict = {}
    client = _client(_recording(seen, issue, 200))

    task = await client.get_issue("RFC-1", "customfield_10051")

    assert seen["params"]["fields"] == (
        "summary,description,reporter,customfield_10051"
    )
    assert task.body == document(Heading(2, (Text("Why"),)))
    assert task.reporter == Person("acc-r", "Rita")
    assert task.change_owner == Person("acc-o", "Owen")


@pytest.mark.asyncio
async def test_without_a_change_owner_field_there_is_no_change_owner() -> None:
    issue = {"key": "RFC-1", "fields": {"summary": "x", "description": None}}

    task = await _client(_recording({}, issue, 200)).get_issue("RFC-1")

    assert task.change_owner is None
    assert task.body == document()


@pytest.mark.asyncio
async def test_a_subtask_keeps_its_marker_as_a_code_paragraph() -> None:
    seen: dict = {}
    source = JiraTaskSource(_client(_recording(seen, {"key": "RFC-2"})))

    await source.create_subtask(
        "RFC-1", "Child",
        document(paragraph(Text("Self-contained body")), Marker("mirror")),
    )

    description = seen["body"]["fields"]["description"]
    assert description["content"][-1] == {
        "type": "paragraph",
        "content": [{"type": "text", "text": "[kestrel:mirror]",
                     "marks": [{"type": "code"}]}],
    }

"""Tests for the controlled Jira Cloud document renderer."""

from __future__ import annotations

import json

import httpx
import pytest

from app.documents import (
    BulletList,
    Code,
    Heading,
    ListItem,
    OrderedList,
    Text,
    document,
    paragraph,
    render_adf,
)
from app.markers import SUBTASK_SENTINEL, SubtaskSentinel
from app.services.jira import JiraClient, JiraTaskSource
from app.services.jira_document import to_text
from app.services.task_source_utils import has_subtask_sentinel


def _client(handler) -> JiraClient:
    """Build a Cloud Jira client against an in-memory HTTP transport."""
    client = JiraClient("https://jira.example", deployment="cloud")
    client._http = httpx.AsyncClient(
        base_url="https://jira.example/rest/api/3",
        transport=httpx.MockTransport(handler),
    )
    return client


def test_adf_keeps_ordered_and_bullet_lists_separate() -> None:
    """Adjacent list styles produce flat independent ADF lists."""
    rendered = render_adf(
        document(
            OrderedList(items=(
                ListItem((paragraph(Text("First")),)),
                ListItem((paragraph(Text("Second")),)),
            )),
            BulletList((
                ListItem((paragraph(Text("Third")),)),
            )),
        )
    )

    assert [node["type"] for node in rendered["content"]] == [
        "orderedList",
        "bulletList",
    ]


def test_to_text_preserves_token_from_adf() -> None:
    """ADF flattening retains the token used by review feedback parsing."""
    adf_document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "[kestrel-review:token] @kestrel approve",
                    }
                ],
            }
        ],
    }

    assert to_text(adf_document) == "[kestrel-review:token] @kestrel approve"


@pytest.mark.asyncio
async def test_cloud_comments_render_documents_as_adf_v3_payloads() -> None:
    """Cloud comments use v3 and render an explicit document structure."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(201, json={"self": "https://jira/c/1"})

    body = document(
        Heading(2, (Text("Review"),)),
        BulletList((
            ListItem((paragraph(Text("Approve with "), Code("token")),)),
        )),
    )
    await _client(handler).add_comment("RFC-1", body)

    assert seen["path"] == "/rest/api/3/issue/RFC-1/comment"
    adf_document = seen["body"]["body"]
    assert adf_document["type"] == "doc"
    assert [node["type"] for node in adf_document["content"]] == [
        "heading",
        "bulletList",
    ]


@pytest.mark.asyncio
async def test_cloud_feedback_normalizes_adf_review_token() -> None:
    """ADF feedback is normalized before review-token classification."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"comments": [_comment()], "total": 1})

    items = await JiraTaskSource(_client(handler)).list_comments("RFC-1")
    assert items[0].body == "@kestrel approve [kestrel-review:abc]"


@pytest.mark.asyncio
async def test_cloud_subtask_marker_survives_adf_round_trip() -> None:
    """Cloud subtasks preserve their marker as a final code paragraph."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return httpx.Response(201, json={"key": "RFC-2"})

    source = JiraTaskSource(_client(handler))
    await source.create_subtask(
        "RFC-1",
        "Child",
        "Self-contained body",
        markers=(SubtaskSentinel(),),
    )

    description = seen["body"]["fields"]["description"]
    last_paragraph = description["content"][-1]
    assert last_paragraph == {
        "type": "paragraph",
        "content": [{
            "type": "text",
            "text": SUBTASK_SENTINEL,
            "marks": [{"type": "code"}],
        }],
    }
    assert has_subtask_sentinel(to_text(description))


def _comment() -> dict:
    """Build an ADF ticket comment containing a review response token."""
    return {
        "id": "1",
        "author": {"displayName": "Jane Reviewer"},
        "created": "2026-01-01T00:00:00.000+0000",
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "@kestrel approve [kestrel-review:abc]",
                        }
                    ],
                }
            ],
        },
    }

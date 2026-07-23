"""Tests for the Jira REST client + TaskSource adapter (feature 003)."""
from __future__ import annotations

import json

import httpx
import pytest

from app.ports import Task
from app.services.jira import JiraClient, JiraError, JiraTaskSource


def _client(handler, **kw) -> JiraClient:
    client = JiraClient("https://jira.example", **kw)
    client._http = httpx.AsyncClient(
        base_url="https://jira.example/rest/api/2",
        transport=httpx.MockTransport(handler),
        auth=client._http.auth,
    )
    return client


@pytest.mark.asyncio
async def test_search_parses_issues_and_paginates() -> None:
    """search() POSTs to /search/jql and follows nextPageToken to the end."""
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append({"path": req.url.path, "method": req.method, "body": body})
        if body.get("nextPageToken") is None:
            return httpx.Response(200, json={
                "issues": [
                    {"key": "RFC-1",
                     "fields": {"summary": "One", "description": "d1"}},
                ],
                "nextPageToken": "tok2",
                "isLast": False,
            })
        return httpx.Response(200, json={
            "issues": [
                {"key": "RFC-2",
                 "fields": {"summary": "Two", "description": None}},
            ],
            "isLast": True,
        })

    page_size = 25
    tasks = await _client(handler, auth="basic", email="e", token="t").search(
        'project = "RFC"', fields=["summary", "description"],
        max_results=page_size,
    )
    assert tasks == [
        Task(ref="RFC-1", title="One", body="d1"),
        Task(ref="RFC-2", title="Two", body=""),
    ]
    assert [s["method"] for s in seen] == ["POST", "POST"]
    assert seen[0]["path"].endswith("/search/jql")
    assert seen[0]["body"]["maxResults"] == page_size
    assert seen[0]["body"]["fields"] == ["summary", "description"]
    assert seen[1]["body"]["nextPageToken"] == "tok2"


@pytest.mark.asyncio
async def test_get_field_returns_value_or_none() -> None:
    """Ensure get_field reads a scalar field, or None when empty."""
    def handler(req: httpx.Request) -> httpx.Response:
        if "customfield_1" in str(req.url):
            return httpx.Response(200, json={
                "key": "RFC-1", "fields": {"customfield_1": "team/svc@dev"}
            })
        return httpx.Response(200, json={"key": "RFC-1", "fields": {}})

    client = _client(handler, auth="basic", email="e", token="t")
    assert await client.get_field("RFC-1", "customfield_1") == "team/svc@dev"
    assert await client.get_field("RFC-1", "missing") is None


@pytest.mark.asyncio
async def test_add_comment_and_attachment() -> None:
    """Ensure comment/attachment hit the right paths and headers."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen[req.url.path] = req.headers.get("x-atlassian-token")
        if req.url.path.endswith("/comment"):
            return httpx.Response(201, json={"self": "https://jira/c/1"})
        return httpx.Response(200, json=[{"id": "1"}])

    client = _client(handler, auth="basic", email="e", token="t")
    assert await client.add_comment("RFC-1", "hi") == "https://jira/c/1"
    await client.add_attachment("RFC-1", "PRD.md", "content")
    assert seen["/rest/api/2/issue/RFC-1/comment"] is None
    # Attachment carries the XSRF-bypass header.
    assert seen["/rest/api/2/issue/RFC-1/attachments"] == "no-check"


@pytest.mark.asyncio
async def test_bearer_auth_sets_header() -> None:
    """Ensure bearer auth sends an Authorization: Bearer header."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"issues": []})

    await _client(handler, auth="bearer", token="pat-123").search(
        "project = RFC", fields=["summary"]
    )
    assert seen["auth"] == "Bearer pat-123"


@pytest.mark.asyncio
async def test_error_does_not_leak_token() -> None:
    """Ensure a raised JiraError never contains the token."""
    with pytest.raises(JiraError) as exc:
        await _client(
            lambda r: httpx.Response(500, text="boom"),
            auth="bearer", token="pat-supersecret",
        ).get_issue("RFC-1")
    assert "pat-supersecret" not in str(exc.value)


@pytest.mark.asyncio
async def test_task_source_publishes_prd_as_attachment() -> None:
    """Ensure JiraTaskSource.publish_refined attaches PRD.md."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        return httpx.Response(200, json=[{"id": "1"}])

    src = JiraTaskSource(_client(handler, auth="basic", email="e", token="t"))
    await src.publish_refined("RFC-1", "the PRD")
    assert seen["path"].endswith("/issue/RFC-1/attachments")
    assert src.deep_link_ref("RFC-1") == "https://jira.example/browse/RFC-1"

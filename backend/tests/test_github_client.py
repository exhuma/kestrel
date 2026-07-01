"""Tests for the GitHub REST client (transport mocked)."""
from __future__ import annotations

import json

import httpx
import pytest

from app.services.exceptions import GitHubError
from app.services.github import GitHubClient, Issue


def _client(handler) -> GitHubClient:
    client = GitHubClient("https://api.github.com", "tok-123")
    client._http = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    return client


@pytest.mark.asyncio
async def test_get_issue_parses_shape() -> None:
    """Ensure get_issue calls the right URL and parses the issue."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(
            200, json={"number": 7, "title": "Bug", "body": "desc"}
        )

    issue = await _client(handler).get_issue("o/r", 7)
    assert issue == Issue(number=7, title="Bug", body="desc")
    assert seen["url"] == "https://api.github.com/repos/o/r/issues/7"
    assert seen["auth"] == "Bearer tok-123"


@pytest.mark.asyncio
async def test_get_default_branch() -> None:
    """Ensure get_default_branch reads default_branch from the repo."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"default_branch": "main"})

    assert await _client(handler).get_default_branch("o/r") == "main"


@pytest.mark.asyncio
async def test_update_issue_sends_body() -> None:
    """Ensure update_issue PATCHes the issue with the new body."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["method"] = req.method
        seen["json"] = json.loads(req.content)
        return httpx.Response(200, json={"number": 7})

    await _client(handler).update_issue("o/r", 7, "new body")
    assert seen["method"] == "PATCH"
    assert seen["json"] == {"body": "new body"}


@pytest.mark.asyncio
async def test_create_pull_request_returns_html_url() -> None:
    """Ensure create_pull_request posts a draft PR and returns its url."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(req.content)
        return httpx.Response(
            201, json={"html_url": "https://github.com/o/r/pull/9"}
        )

    url = await _client(handler).create_pull_request(
        "o/r", head="b", base="main", title="T", body="B"
    )
    assert url == "https://github.com/o/r/pull/9"
    assert seen["json"] == {
        "title": "T",
        "head": "b",
        "base": "main",
        "body": "B",
        "draft": True,
    }


@pytest.mark.asyncio
async def test_non_2xx_raises_github_error() -> None:
    """Ensure a non-2xx response raises GitHubError."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    with pytest.raises(GitHubError):
        await _client(handler).get_issue("o/r", 7)

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
async def test_no_token_omits_authorization_header() -> None:
    """Ensure an unset token sends no Authorization header at all.

    Regression: a blank token used to render "Bearer " — an illegal
    header value that made httpx raise LocalProtocolError before the
    request left the process. With no token we now fall back to
    unauthenticated access instead of crashing.
    """
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(
            200, json={"number": 7, "title": "Bug", "body": "desc"}
        )

    client = GitHubClient("https://api.github.com", "")
    client._http = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    await client.get_issue("o/r", 7)
    assert seen["auth"] is None


@pytest.mark.asyncio
async def test_non_2xx_raises_github_error() -> None:
    """Ensure a non-2xx response raises GitHubError."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    with pytest.raises(GitHubError):
        await _client(handler).get_issue("o/r", 7)


@pytest.mark.asyncio
async def test_404_with_token_hints_at_access_or_existence() -> None:
    """Ensure a 404 while authenticated points at access/existence."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    with pytest.raises(GitHubError) as exc:
        await _client(handler).get_issue("o/r", 7)  # _client sends a token
    assert "lack access" in str(exc.value)


@pytest.mark.asyncio
async def test_404_without_token_hints_at_missing_config() -> None:
    """Ensure a 404 while unauthenticated points at the missing token."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = GitHubClient("https://api.github.com", "")
    client._http = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GitHubError) as exc:
        await client.get_issue("o/r", 7)
    assert "KESTREL_GITHUB_TOKEN" in str(exc.value)


@pytest.mark.asyncio
async def test_error_body_is_truncated() -> None:
    """Ensure a large error response body is truncated in the GitHubError."""
    big = "A" * 5000

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=big)

    with pytest.raises(GitHubError) as exc:
        await _client(handler).get_issue("o/r", 7)
    message = str(exc.value)
    assert "truncated" in message
    # The full body must not survive into the error/log surface.
    assert big not in message
    assert message.count("A") <= 600

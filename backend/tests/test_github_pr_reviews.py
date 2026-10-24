"""Tests for GitHubCodeHost's change-request state read and URL parsing."""
from __future__ import annotations

import httpx
import pytest

from app.services.change_requests import change_request_number
from app.services.github import GitHubClient, GitHubCodeHost

_GITHUB_PR_NUMBER = 42
_GITLAB_MR_NUMBER = 7
_PR_NUMBER = 9


def _client(handler) -> GitHubClient:
    client = GitHubClient("https://api.github.com", "tok-123")
    client._http = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    return client


def _pr_router(*, pr: dict | None = None) -> object:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pr or {})

    return handler


def test_change_request_number_parses_github_pull_url() -> None:
    """Ensure a well-formed GitHub PR URL yields its trailing number."""
    number = change_request_number("https://github.com/o/r/pull/42")
    assert number == _GITHUB_PR_NUMBER


def test_change_request_number_parses_gitlab_mr_url() -> None:
    """Ensure a GitLab-shaped merge-request URL also parses."""
    number = change_request_number(
        "https://gitlab.internal/group/svc/-/merge_requests/7"
    )
    assert number == _GITLAB_MR_NUMBER


def test_change_request_number_returns_none_for_malformed_or_empty() -> None:
    """Ensure a malformed/empty url never raises, returns None."""
    assert change_request_number("") is None
    assert change_request_number("not a url") is None
    assert change_request_number("https://github.com/o/r/issues/5") is None


@pytest.mark.asyncio
async def test_get_change_request_open() -> None:
    """Ensure an open, unmerged PR maps to state="open"."""
    handler = _pr_router(pr={"state": "open", "merged": False,
                              "html_url": "https://github.com/o/r/pull/9"})
    host = GitHubCodeHost(_client(handler), "https://github.com")
    cr = await host.get_change_request("o/r", _PR_NUMBER)
    assert cr.state == "open"
    assert cr.number == _PR_NUMBER
    assert cr.url == "https://github.com/o/r/pull/9"


@pytest.mark.asyncio
async def test_get_change_request_merged() -> None:
    """Ensure merged=true takes priority over state=closed."""
    handler = _pr_router(pr={"state": "closed", "merged": True})
    host = GitHubCodeHost(_client(handler), "https://github.com")
    cr = await host.get_change_request("o/r", _PR_NUMBER)
    assert cr.state == "merged"


@pytest.mark.asyncio
async def test_get_change_request_closed_unmerged() -> None:
    """Ensure a closed, never-merged PR maps to state="closed"."""
    handler = _pr_router(pr={"state": "closed", "merged": False})
    host = GitHubCodeHost(_client(handler), "https://github.com")
    cr = await host.get_change_request("o/r", _PR_NUMBER)
    assert cr.state == "closed"

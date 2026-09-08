"""Tests for GitHubCodeHost's PR-review read/acknowledge (feature 013, US3).

Split from ``test_github_ports.py`` to keep that module under the repo's
module-length ceiling — mirrors the ``github_reviews``/``github_codehost``
split in ``app/services``.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.ports import Feedback
from app.services.github import (
    GitHubClient,
    GitHubCodeHost,
    change_request_number,
)

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


def _comment(comment_id=1, body="hi", login="octocat",
             created="2026-01-01T00:00:00Z", user_type="User") -> dict:
    return {
        "id": comment_id, "body": body,
        "user": {"login": login, "type": user_type},
        "created_at": created,
    }


def _pr_router(
    *, pr: dict | None = None, conversation=None, reviews=None,
    review_comments=None,
) -> object:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/comments") and "/pulls/" not in path:
            return httpx.Response(200, json=conversation or [])
        if path.endswith("/reviews"):
            return httpx.Response(200, json=reviews or [])
        if path.endswith("/comments") and "/pulls/" in path:
            return httpx.Response(200, json=review_comments or [])
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


@pytest.mark.asyncio
async def test_list_review_comments_merges_and_tags_origin() -> None:
    """Ensure conversation + review + inline comments all surface as
    origin="review", each with a distinct external_id prefix."""
    handler = _pr_router(
        conversation=[_comment(comment_id=1, body="conv",
                                created="2026-01-01T00:00:00Z")],
        reviews=[{
            "id": 55, "body": "review summary",
            "user": {"login": "reviewer"},
            "submitted_at": "2026-01-02T00:00:00Z",
        }],
        review_comments=[_comment(comment_id=2, body="inline",
                                   created="2026-01-03T00:00:00Z")],
    )
    host = GitHubCodeHost(_client(handler), "https://github.com")
    items = await host.list_review_comments("o/r", _PR_NUMBER)
    assert {i.origin for i in items} == {"review"}
    assert [i.body for i in items] == ["conv", "review summary", "inline"]
    assert items[0].external_id == "gh-pr-comment:o/r#1"
    assert items[1].external_id == "gh-pr-review:o/r#55"
    assert items[2].external_id == "gh-pr-review-comment:o/r#2"


@pytest.mark.asyncio
async def test_list_review_comments_excludes_empty_review_body() -> None:
    """Ensure a review with no summary text (an approve with no comment)
    never surfaces as Feedback."""
    handler = _pr_router(reviews=[{
        "id": 55, "body": "", "user": {"login": "reviewer"},
        "submitted_at": "2026-01-02T00:00:00Z",
    }])
    host = GitHubCodeHost(_client(handler), "https://github.com")
    items = await host.list_review_comments("o/r", _PR_NUMBER)
    assert items == []


@pytest.mark.asyncio
async def test_list_review_comments_since_cursor_excludes_prior_item() -> None:
    """Ensure a second call with the first call's newest cursor never
    re-returns that same item (round-trip exclusivity)."""
    handler = _pr_router(
        conversation=[
            _comment(comment_id=1, created="2026-01-01T00:00:00Z"),
            _comment(comment_id=2, created="2026-01-02T00:00:00Z"),
        ],
    )
    host = GitHubCodeHost(_client(handler), "https://github.com")
    first = await host.list_review_comments("o/r", _PR_NUMBER)
    cursor = first[-1].created_at.isoformat()

    second = await host.list_review_comments("o/r", _PR_NUMBER, since=cursor)

    assert second == []


@pytest.mark.asyncio
async def test_codehost_acknowledge_reacts_to_pr_conversation_comment() -> None:
    """Ensure a PR-conversation comment reacts via the issues endpoint."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"id": 1})

    host = GitHubCodeHost(_client(handler), "https://github.com")
    feedback = Feedback(
        external_id="gh-pr-comment:o/r#3", origin="review",
        author="octocat", body="hi", created_at=datetime.now(timezone.utc),
    )
    assert await host.acknowledge(feedback) is True
    assert seen["url"].endswith("/repos/o/r/issues/comments/3/reactions")


@pytest.mark.asyncio
async def test_codehost_acknowledge_reacts_to_inline_review_comment() -> None:
    """Ensure an inline review comment reacts via the pulls endpoint."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"id": 1})

    host = GitHubCodeHost(_client(handler), "https://github.com")
    feedback = Feedback(
        external_id="gh-pr-review-comment:o/r#4", origin="review",
        author="octocat", body="hi", created_at=datetime.now(timezone.utc),
    )
    assert await host.acknowledge(feedback) is True
    assert seen["url"].endswith("/repos/o/r/pulls/comments/4/reactions")


@pytest.mark.asyncio
async def test_codehost_acknowledge_review_summary_has_no_endpoint() -> None:
    """Ensure a review's own summary comment (no reaction endpoint on
    GitHub) returns False without any call."""

    def handler(_req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not call GitHub")

    host = GitHubCodeHost(_client(handler), "https://github.com")
    feedback = Feedback(
        external_id="gh-pr-review:o/r#55", origin="review",
        author="octocat", body="hi", created_at=datetime.now(timezone.utc),
    )
    assert await host.acknowledge(feedback) is False

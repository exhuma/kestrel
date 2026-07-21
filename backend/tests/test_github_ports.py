"""Tests for the GitHub TaskSource / CodeHost port adapters (feature 003)."""
from __future__ import annotations

import httpx
import pytest

from app.ports import Task
from app.services.github import (
    GitHubClient,
    GitHubCodeHost,
    GitHubTaskSource,
    parse_github_ref,
)
from app.services.workflow_text import has_sentinel


def _client(handler) -> GitHubClient:
    client = GitHubClient("https://api.github.com", "tok-123")
    client._http = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    return client


def test_parse_github_ref() -> None:
    """Ensure a GitHub task_ref splits into (repo, number)."""
    assert parse_github_ref("o/r#7") == ("o/r", 7)
    assert parse_github_ref("owner/deep/repo#42") == ("owner/deep/repo", 42)
    with pytest.raises(ValueError):
        parse_github_ref("RFC-123")


@pytest.mark.asyncio
async def test_task_source_get_task_and_comment() -> None:
    """Ensure get_task/post_comment address the ref's repo and number."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen[req.method] = str(req.url)
        if req.method == "GET":
            return httpx.Response(
                200, json={"number": 7, "title": "Bug", "body": "b"}
            )
        return httpx.Response(201, json={"html_url": "https://c/1"})

    src = GitHubTaskSource(_client(handler))
    task = await src.get_task("o/r#7")
    assert task == Task(ref="o/r#7", title="Bug", body="b")
    assert await src.post_comment("o/r#7", "hi") == "https://c/1"
    assert seen["GET"].endswith("/repos/o/r/issues/7")
    assert seen["POST"].endswith("/repos/o/r/issues/7/comments")


@pytest.mark.asyncio
async def test_publish_refined_updates_issue_with_sentinel() -> None:
    """Ensure publish_refined PATCHes the body + appends the sentinel."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["method"] = req.method
        seen["url"] = str(req.url)
        seen["body"] = req.read().decode()
        return httpx.Response(200, json={})

    src = GitHubTaskSource(_client(handler))
    await src.publish_refined("o/r#7", "PRD text")
    assert seen["method"] == "PATCH"
    assert seen["url"].endswith("/repos/o/r/issues/7")
    assert "PRD text" in seen["body"]
    # The persisted body carries the refined sentinel.
    import json

    assert has_sentinel(json.loads(seen["body"])["body"])


@pytest.mark.asyncio
async def test_attach_is_noop() -> None:
    """Ensure GitHub attach() is a no-op (no HTTP call)."""

    def handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("attach must not call GitHub")

    assert await GitHubTaskSource(_client(handler)).attach(
        "o/r#7", "PRD.md", "x"
    ) is None


def test_code_host_clone_remote() -> None:
    """Ensure clone_remote composes git_base/repo.git."""
    host = GitHubCodeHost(
        _client(lambda r: httpx.Response(200)), "https://github.com"
    )
    assert host.clone_remote("o/r") == "https://github.com/o/r.git"


@pytest.mark.asyncio
async def test_code_host_open_change_request_opens_draft_pr() -> None:
    """Ensure open_change_request opens a draft pull request with the body."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = req.read().decode()
        return httpx.Response(201, json={"html_url": "https://pr/9"})

    host = GitHubCodeHost(_client(handler), "https://github.com")
    url = await host.open_change_request(
        "o/r", head="kestrel/x", base="main", title="T", body="Closes #7"
    )
    assert url == "https://pr/9"
    assert seen["url"].endswith("/repos/o/r/pulls")
    import json

    payload = json.loads(seen["body"])
    assert payload["draft"] is True
    assert payload["body"] == "Closes #7"

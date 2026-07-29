"""Tests for the GitHub TaskSource / CodeHost port adapters (feature 003)."""
from __future__ import annotations

import httpx
import pytest

from app.config_models import TaskSourceConfig
from app.ports import LifecycleEvent, Task
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


def test_git_credential_uses_x_access_token() -> None:
    """Ensure GitHub git auth is x-access-token:<token>."""
    host = GitHubCodeHost(_client(lambda r: httpx.Response(200)), "https://gh")
    assert host.git_credential() == ("x-access-token", "tok-123")


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
        "o/r#7", "shot.png", b"\x89PNG", "image/png"
    ) is None


@pytest.mark.asyncio
async def test_transition_start_adds_in_progress_label() -> None:
    """Ensure a "start" event adds the configured in-progress label."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["method"] = req.method
        seen["url"] = str(req.url)
        seen["body"] = req.read().decode()
        return httpx.Response(200, json=[])

    src = GitHubTaskSource(_client(handler))
    ok = await src.transition("o/r#7", LifecycleEvent(kind="start"))
    assert ok is True
    assert seen["url"].endswith("/repos/o/r/issues/7/labels")
    assert "kestrel-in-progress" in seen["body"]


@pytest.mark.asyncio
async def test_transition_done_removes_label_and_never_closes() -> None:
    """Ensure "done" only removes the label — never PATCHes issue state."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["method"] = req.method
        seen["url"] = str(req.url)
        return httpx.Response(200, json=[])

    src = GitHubTaskSource(_client(handler))
    ok = await src.transition("o/r#7", LifecycleEvent(kind="done"))
    assert ok is True
    assert seen["method"] == "DELETE"
    assert seen["url"].endswith(
        "/repos/o/r/issues/7/labels/kestrel-in-progress"
    )


@pytest.mark.asyncio
async def test_transition_failed_swaps_label() -> None:
    """Ensure a failure terminal removes in-progress, adds the failed label."""
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, str(req.url)))
        return httpx.Response(200, json=[])

    src = GitHubTaskSource(_client(handler))
    ok = await src.transition("o/r#7", LifecycleEvent(kind="failed"))
    assert ok is True
    assert ("DELETE", "https://api.github.com/repos/o/r/issues/7/"
            "labels/kestrel-in-progress") in calls
    assert any(m == "POST" and u.endswith("/labels") for m, u in calls)


@pytest.mark.asyncio
async def test_transition_uses_config_for_resolver() -> None:
    """Ensure per-repo config (custom labels) is resolved via config_for."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = req.read().decode()
        return httpx.Response(200, json=[])

    cfg = TaskSourceConfig(
        type="github", watched_repos=["o/r"], in_progress_label="wip"
    )
    src = GitHubTaskSource(
        _client(handler), config_for=lambda repo: cfg if repo == "o/r" else None
    )
    await src.transition("o/r#7", LifecycleEvent(kind="start"))
    assert "wip" in seen["body"]


@pytest.mark.asyncio
async def test_transition_swallows_errors_and_returns_false() -> None:
    """Ensure a failing API call returns False rather than raising."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    src = GitHubTaskSource(_client(handler))
    ok = await src.transition("o/r#7", LifecycleEvent(kind="start"))
    assert ok is False


def test_supports_time_spent_is_always_false() -> None:
    """Ensure GitHub never claims native time-tracking support."""
    src = GitHubTaskSource(_client(lambda r: httpx.Response(200)))
    assert src.supports_time_spent() is False


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

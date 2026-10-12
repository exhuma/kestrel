"""Contract tests for ``check_health()`` across every adapter (feature 014).

Mirrors contracts/health-check-port.md: success -> True; a failure (HTTP
error, connection failure) raises, so the health service can log why the
source is unreachable instead of losing the reason.
"""
from __future__ import annotations

import httpx
import pytest

from app.services.exceptions import GitHubError
from app.services.github import GitHubClient
from app.services.gitlab import GitLabCodeHost, GitLabError
from app.services.jira import JiraClient, JiraError
from app.services.local_task_source import LocalTaskSource


def _github(handler) -> GitHubClient:
    client = GitHubClient("https://api.github.com", "tok-123")
    client._http = httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    return client


def _jira(handler) -> JiraClient:
    client = JiraClient("https://jira.example", token="t")
    client._http = httpx.AsyncClient(
        base_url="https://jira.example/rest/api/2",
        transport=httpx.MockTransport(handler),
        auth=client._http.auth,
    )
    return client


def _gitlab(handler, is_gitea: bool = False) -> GitLabCodeHost:
    host = GitLabCodeHost(
        "https://gitlab.internal", "glpat-secret", is_gitea=is_gitea
    )
    host._http = httpx.AsyncClient(
        base_url="https://gitlab.internal/api/v4",
        transport=httpx.MockTransport(handler),
    )
    return host


@pytest.mark.asyncio
async def test_github_check_health_true_on_success() -> None:
    """Ensure a 200 from GET /user reports healthy."""
    client = _github(lambda _req: httpx.Response(200, json={"login": "me"}))
    assert await client.check_health() is True


@pytest.mark.asyncio
async def test_github_check_health_raises_on_http_error() -> None:
    """Ensure a 401 raises with the status, so the reason can be logged."""
    client = _github(lambda _req: httpx.Response(401, json={}))
    with pytest.raises(GitHubError, match="401"):
        await client.check_health()


@pytest.mark.asyncio
async def test_github_check_health_raises_on_connection_failure() -> None:
    """Ensure a transport-level failure surfaces as itself."""

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=req)

    client = _github(handler)
    with pytest.raises(httpx.ConnectError, match="connection refused"):
        await client.check_health()


@pytest.mark.asyncio
async def test_jira_check_health_true_on_success() -> None:
    """Ensure a 200 from GET /myself reports healthy."""
    client = _jira(lambda _req: httpx.Response(200, json={"accountId": "1"}))
    assert await client.check_health() is True


@pytest.mark.asyncio
async def test_jira_check_health_raises_on_http_error() -> None:
    """Ensure a 403 raises with the status, so the reason can be logged."""
    client = _jira(lambda _req: httpx.Response(403, json={}))
    with pytest.raises(JiraError, match="403"):
        await client.check_health()


@pytest.mark.asyncio
async def test_jira_check_health_raises_on_connection_failure() -> None:
    """Ensure a TLS/DNS/connect failure surfaces as itself."""

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("certificate verify failed", request=req)

    with pytest.raises(httpx.ConnectError, match="certificate"):
        await _jira(handler).check_health()


@pytest.mark.asyncio
async def test_gitlab_check_health_true_on_success() -> None:
    """Ensure a 200 from GET /user reports healthy."""
    host = _gitlab(lambda _req: httpx.Response(200, json={"id": 1}))
    assert await host.check_health() is True


@pytest.mark.asyncio
async def test_gitlab_check_health_raises_on_http_error() -> None:
    """Ensure a 401 raises with the status, so the reason can be logged."""
    host = _gitlab(lambda _req: httpx.Response(401, json={}))
    with pytest.raises(GitLabError, match="401"):
        await host.check_health()


@pytest.mark.asyncio
async def test_gitea_check_health_uses_the_same_call() -> None:
    """Ensure the is_gitea flag doesn't change check_health's behavior
    (this adapter already assumes GitLab-API-compatible endpoints for
    both — see get_default_branch)."""
    host = _gitlab(
        lambda _req: httpx.Response(200, json={"id": 1}), is_gitea=True
    )
    assert await host.check_health() is True


@pytest.mark.asyncio
async def test_local_task_check_health_is_always_true_with_no_io(
    tmp_path,
) -> None:
    """Ensure the local task adapter reports healthy without touching disk."""
    source = LocalTaskSource(str(tmp_path / "does-not-exist"))
    assert await source.check_health() is True

"""Tests for the self-hosted GitLab CodeHost adapter (feature 003)."""
from __future__ import annotations

import json

import httpx
import pytest

from app.services.gitlab import GitLabCodeHost, GitLabError


def _host(handler, token: str = "glpat-secret") -> GitLabCodeHost:
    host = GitLabCodeHost("https://gitlab.internal", token)
    host._http = httpx.AsyncClient(
        base_url="https://gitlab.internal/api/v4",
        transport=httpx.MockTransport(handler),
    )
    return host


def test_clone_remote_uses_base_url() -> None:
    """Ensure clone_remote composes the self-hosted base URL."""
    host = _host(lambda r: httpx.Response(200))
    assert host.clone_remote("group/svc") == (
        "https://gitlab.internal/group/svc.git"
    )


def test_git_credential_uses_oauth2_scheme() -> None:
    """Ensure GitLab git auth is oauth2:<pat> (not GitHub's x-access-token)."""
    host = _host(lambda r: httpx.Response(200), token="glpat-secret")
    assert host.git_credential() == ("oauth2", "glpat-secret")


@pytest.mark.asyncio
async def test_get_default_branch_url_encodes_project() -> None:
    """Ensure the project path is URL-encoded and default_branch parsed."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["token"] = req.headers.get("private-token")
        return httpx.Response(200, json={"default_branch": "main"})

    assert await _host(handler).get_default_branch("group/svc") == "main"
    assert "/projects/group%2Fsvc" in seen["url"]
    assert seen["token"] == "glpat-secret"


@pytest.mark.asyncio
async def test_get_default_branch_raises_on_unreachable_project() -> None:
    """Ensure an unreachable project raises (→ unresolved-repo upstream)."""
    host = _host(lambda r: httpx.Response(404, text="Not Found"))
    with pytest.raises(GitLabError):
        await host.get_default_branch("group/missing")


@pytest.mark.asyncio
async def test_open_change_request_opens_draft_merge_request() -> None:
    """Ensure a draft MR uses the Draft: title prefix and returns web_url."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["payload"] = json.loads(req.read().decode())
        return httpx.Response(
            201, json={"web_url": "https://gitlab.internal/mr/3"}
        )

    url = await _host(handler).open_change_request(
        "group/svc",
        head="kestrel/RFC-1",
        base="main",
        title="Implement RFC-1",
        body="Ref RFC-1",
    )
    assert url == "https://gitlab.internal/mr/3"
    assert "/projects/group%2Fsvc/merge_requests" in seen["url"]
    assert seen["payload"]["title"] == "Draft: Implement RFC-1"
    assert seen["payload"]["source_branch"] == "kestrel/RFC-1"
    assert seen["payload"]["target_branch"] == "main"


@pytest.mark.asyncio
async def test_non_draft_merge_request_has_plain_title() -> None:
    """Ensure a non-draft MR omits the Draft: prefix."""
    def handler(req: httpx.Request) -> httpx.Response:
        payload = json.loads(req.read().decode())
        assert payload["title"] == "Implement RFC-1"
        return httpx.Response(
            201, json={"web_url": "https://gitlab.internal/mr/4"}
        )

    await _host(handler).open_change_request(
        "group/svc", head="h", base="main", title="Implement RFC-1",
        body="", draft=False,
    )


@pytest.mark.asyncio
async def test_token_not_leaked_in_error() -> None:
    """Ensure the PRIVATE-TOKEN never appears in a raised error."""
    with pytest.raises(GitLabError) as exc:
        await _host(
            lambda r: httpx.Response(500, text="boom"),
            token="glpat-supersecret",
        ).get_default_branch("group/svc")
    assert "glpat-supersecret" not in str(exc.value)

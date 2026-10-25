"""Tests for the self-hosted GitLab CodeHost adapter (feature 003)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.documents import Text, document, paragraph
from app.services.gitlab import GitLabCodeHost, GitLabError

_MR_NUMBER = 12
_NOW = datetime.now(timezone.utc)


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
        body=document(paragraph(Text("Ref RFC-1"))),
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
        body=document(), draft=False,
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


# ---- change-request read + review feedback (feature 013, US3) ---------


@pytest.mark.asyncio
async def test_get_change_request_maps_opened_to_open() -> None:
    """Ensure GitLab's "opened" state maps onto the port's "open"."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"state": "opened", "web_url": "https://gl/mr/12"}
        )

    cr = await _host(handler).get_change_request("group/svc", _MR_NUMBER)
    assert cr.state == "open"
    assert cr.number == _MR_NUMBER
    assert cr.url == "https://gl/mr/12"


@pytest.mark.asyncio
async def test_get_change_request_maps_merged_and_closed() -> None:
    """Ensure "merged" and "closed" pass through unchanged."""
    merged = await _host(
        lambda r: httpx.Response(200, json={"state": "merged"})
    ).get_change_request("group/svc", _MR_NUMBER)
    closed = await _host(
        lambda r: httpx.Response(200, json={"state": "closed"})
    ).get_change_request("group/svc", _MR_NUMBER)
    assert merged.state == "merged"
    assert closed.state == "closed"


def _note(note_id=1, body="hi", username="alice",
          created="2026-01-01T00:00:00Z", system=False) -> dict:
    return {
        "id": note_id, "body": body, "system": system,
        "author": {"username": username}, "created_at": created,
    }


@pytest.mark.asyncio
async def test_required_ci_statuses_use_newest_pipeline_jobs() -> None:
    """Required GitLab job results normalize absent, pass, and failure."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/pipelines"):
            return httpx.Response(200, json=[{"id": 7}])
        return httpx.Response(
            200,
            json=[
                {"name": "tests", "status": "success"},
                {"name": "lint", "status": "failed"},
            ],
            headers={"x-next-page": ""},
        )

    statuses = await _host(handler).required_ci_statuses(
        "group/svc", _MR_NUMBER, ["tests", "lint", "ui"]
    )
    assert [status.state for status in statuses] == [
        "passed", "failed", "pending"
    ]

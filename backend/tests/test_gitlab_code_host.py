"""Tests for the self-hosted GitLab CodeHost adapter (feature 003)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.ports import Feedback
from app.services.gitlab import GitLabCodeHost, GitLabError

_MR_NUMBER = 12
_NOW = datetime.now(timezone.utc)


def _host(
    handler, token: str = "glpat-secret", is_gitea: bool = False,
) -> GitLabCodeHost:
    host = GitLabCodeHost(
        "https://gitlab.internal", token, is_gitea=is_gitea
    )
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
async def test_list_review_comments_maps_notes_to_feedback() -> None:
    """Ensure MR notes map to review-origin Feedback with a minted id."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=[_note(note_id=9, body="please fix this")]
        )

    items = await _host(handler).list_review_comments(
        "group/svc", _MR_NUMBER
    )
    assert items == [
        Feedback(
            external_id="gl-note:group/svc#12#9",
            origin="review", author="alice", body="please fix this",
            created_at=items[0].created_at,
        )
    ]


@pytest.mark.asyncio
async def test_list_review_comments_excludes_system_notes() -> None:
    """Ensure a system-generated note (activity log, not review feedback)
    never surfaces as Feedback."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                _note(note_id=1, system=True),
                _note(note_id=2, system=False),
            ],
        )

    items = await _host(handler).list_review_comments(
        "group/svc", _MR_NUMBER
    )
    assert [i.external_id for i in items] == ["gl-note:group/svc#12#2"]


@pytest.mark.asyncio
async def test_list_review_comments_since_cursor_excludes_prior_item() -> None:
    """Ensure a second call with the first call's newest cursor never
    re-returns that same note (round-trip exclusivity)."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                _note(note_id=1, created="2026-01-01T00:00:00Z"),
                _note(note_id=2, created="2026-01-02T00:00:00Z"),
            ],
        )

    host = _host(handler)
    first = await host.list_review_comments("group/svc", _MR_NUMBER)
    cursor = first[-1].created_at.isoformat()

    second = await host.list_review_comments(
        "group/svc", _MR_NUMBER, since=cursor
    )

    assert second == []


@pytest.mark.asyncio
async def test_list_review_comments_returns_empty_for_gitea() -> None:
    """Ensure a Gitea-backed instance never calls the GitLab-only notes
    endpoint — degrades to an empty list instead."""

    def handler(_req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not call a GitLab-only endpoint")

    host = _host(handler, is_gitea=True)
    assert await host.list_review_comments("group/svc", _MR_NUMBER) == []


@pytest.mark.asyncio
async def test_acknowledge_awards_the_eyes_emoji() -> None:
    """Ensure acknowledge hits the award_emoji endpoint for the right
    project/MR/note, recovered from the Feedback's external_id."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["body"] = req.read().decode()
        return httpx.Response(201, json={"id": 1})

    feedback = Feedback(
        external_id="gl-note:group/svc#12#9", origin="review",
        author="alice", body="hi", created_at=_NOW,
    )
    ok = await _host(handler).acknowledge(feedback)
    assert ok is True
    assert seen["url"].endswith(
        "/projects/group%2Fsvc/merge_requests/12/notes/9/award_emoji"
    )
    assert "eyes" in seen["body"]


@pytest.mark.asyncio
async def test_acknowledge_returns_false_for_unparseable_external_id() -> None:
    """Ensure a non-note external_id (no match) returns False, no call."""

    def handler(_req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not call GitLab")

    feedback = Feedback(
        external_id="gh-issue-comment:o/r#5", origin="review",
        author="alice", body="hi", created_at=_NOW,
    )
    assert await _host(handler).acknowledge(feedback) is False


@pytest.mark.asyncio
async def test_acknowledge_returns_false_for_gitea() -> None:
    """Ensure a Gitea-backed instance never awards an emoji (no such
    concept implemented against Gitea's API this feature)."""

    def handler(_req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not call Gitea")

    feedback = Feedback(
        external_id="gl-note:group/svc#12#9", origin="review",
        author="alice", body="hi", created_at=_NOW,
    )
    assert await _host(handler, is_gitea=True).acknowledge(feedback) is False

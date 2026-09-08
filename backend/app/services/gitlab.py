"""Async GitLab REST client + ``CodeHost`` adapter (feature 003).

The self-hostable code host for Jira-resolved repositories: kestrel is sovereign
by design, so a resolved repo can live on an on-prem GitLab and open a **merge
request** there. Gitea/Forgejo is the same port with different endpoints.
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote

import httpx

from app.ports import ChangeRequest, Feedback
from app.services.exceptions import GitError
from app.services.feedback.timeparse import parse_iso

#: Prefix minted onto every MR-note ``Feedback.external_id`` (feature 013,
#: US3) — carries the repo and MR iid so ``acknowledge`` can reconstruct
#: the award-emoji endpoint from just the ``Feedback`` object.
_NOTE_ID_PREFIX = "gl-note:"

#: GitLab's own three MR states, mapped 1:1 onto ``ChangeRequest.state``
#: ("opened" is GitLab's spelling; the port uses "open" everywhere else).
_STATE_MAP: dict[str, Literal["open", "merged", "closed"]] = {
    "opened": "open", "merged": "merged", "closed": "closed",
}


class GitLabError(GitError):
    """A GitLab REST call failed."""


def _parse_note_external_id(external_id: str) -> tuple[str, int, int] | None:
    """Recover ``(repo, mr_iid, note_id)`` from a minted MR-note id."""
    if not external_id.startswith(_NOTE_ID_PREFIX):
        return None
    rest = external_id[len(_NOTE_ID_PREFIX):]
    repo_and_iid, _, note_id = rest.rpartition("#")
    repo, _, mr_iid = repo_and_iid.rpartition("#")
    if not repo or not mr_iid.isdigit() or not note_id.isdigit():
        return None
    return repo, int(mr_iid), int(note_id)


def _note_feedback(repo: str, number: int, note: dict) -> Feedback | None:
    """Map one raw MR note to review-origin ``Feedback``.

    System notes (GitLab's auto-generated activity log entries — "changed
    the description", "assigned to @x") are excluded here, at the source,
    the same way GitHub's Bot-typed comments are (research.md R6): they
    are not reviewer-authored signal.
    """
    if note.get("system"):
        return None
    author = note.get("author") or {}
    return Feedback(
        external_id=f"{_NOTE_ID_PREFIX}{repo}#{number}#{note['id']}",
        origin="review",
        author=author.get("username", ""),
        body=note.get("body") or "",
        created_at=parse_iso(note["created_at"]),
    )


class GitLabCodeHost:
    """``CodeHost`` over the GitLab REST API (merge requests).

    :param base_url: Instance base URL, e.g. ``https://gitlab.internal``.
    :param token: Personal access token (sent as ``PRIVATE-TOKEN``; never
        logged).
    :param is_gitea: Whether this instance actually points at a Gitea/
        Forgejo server (feature 013, US3) — Gitea shares GitLab's
        merge-request-based ``CodeHost`` shape for everything this class
        implemented before feature 013, but review-comment reading is not
        implemented against its API this feature (plan.md's "Not added"
        note), so ``list_review_comments``/``acknowledge`` degrade to a
        safe no-op rather than calling a GitLab-only endpoint.
    """

    def __init__(
        self, base_url: str, token: str, verify: bool = True,
        is_gitea: bool = False,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._is_gitea = is_gitea
        self._http = httpx.AsyncClient(
            base_url=f"{self._base}/api/v4", verify=verify
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["PRIVATE-TOKEN"] = self._token
        return headers

    async def _request(self, method: str, path: str, **kw) -> httpx.Response:
        resp = await self._http.request(
            method, path, headers=self._headers(), **kw
        )
        if resp.status_code >= 300:
            # Redact: PRIVATE-TOKEN never appears in the message.
            raise GitLabError(
                f"{method} {path} -> {resp.status_code}: {resp.text}"
            )
        return resp

    @staticmethod
    def _pid(repo: str) -> str:
        """URL-encode a ``group/project`` path into a GitLab project id."""
        return quote(repo, safe="")

    async def get_default_branch(self, repo: str) -> str:
        """Return the project's default branch."""
        resp = await self._request("GET", f"/projects/{self._pid(repo)}")
        return resp.json()["default_branch"]

    async def check_health(self) -> bool:
        """Best-effort reachability + auth probe (feature 014).

        A single cheap, project-independent, authenticated call — same
        endpoint shape for a real GitLab instance and a Gitea instance
        (this adapter already assumes GitLab-API-compatible endpoints for
        both, e.g. ``get_default_branch``). Never raises: any failure
        (network, auth, timeout, malformed response) is caught and
        reported as ``False``.
        """
        try:
            await self._request("GET", "/user")
        except Exception:  # noqa: BLE001 — health checks never raise
            return False
        return True

    def clone_remote(self, repo: str) -> str:
        """The HTTPS git remote a worktree clones/fetches from."""
        return f"{self._base}/{repo}.git"

    def git_credential(self) -> tuple[str, str]:
        """``oauth2`` + the PAT — GitLab's git-over-HTTPS token scheme."""
        return ("oauth2", self._token)

    async def open_change_request(
        self,
        repo: str,
        *,
        head: str,
        base: str,
        title: str,
        body: str,
        draft: bool = True,
    ) -> str:
        """Open a merge request and return its ``web_url``.

        GitLab signals a draft MR with a ``Draft:`` title prefix.
        """
        mr_title = f"Draft: {title}" if draft else title
        resp = await self._request(
            "POST",
            f"/projects/{self._pid(repo)}/merge_requests",
            json={
                "source_branch": head,
                "target_branch": base,
                "title": mr_title,
                "description": body,
            },
        )
        return resp.json()["web_url"]

    async def get_change_request(
        self, repo: str, number: int
    ) -> ChangeRequest:
        """Fetch a merge request's lifecycle state (feature 013, US3/US4)."""
        resp = await self._request(
            "GET",
            f"/projects/{self._pid(repo)}/merge_requests/{number}",
        )
        data = resp.json()
        state = _STATE_MAP.get(data.get("state", ""), "open")
        return ChangeRequest(
            number=number, state=state, url=data.get("web_url") or ""
        )

    async def list_review_comments(
        self, repo: str, number: int, since: str | None = None
    ) -> list[Feedback]:
        """Every reviewer-authored note on the MR (feature 013, US3).

        Not implemented against Gitea's API this feature (degraded, not
        wrong) — see plan.md's "Not added" note; a Gitea-backed instance
        always returns ``[]`` here.
        """
        if self._is_gitea:
            return []
        resp = await self._request(
            "GET",
            f"/projects/{self._pid(repo)}/merge_requests/{number}/notes",
            params={"order_by": "created_at", "sort": "asc"},
        )
        cutoff = parse_iso(since) if since else None
        mapped = (
            _note_feedback(repo, number, note) for note in resp.json()
        )
        return [
            item for item in mapped
            if item is not None and (cutoff is None or item.created_at > cutoff)
        ]

    async def acknowledge(
        self, feedback: Feedback, token: str = "eyes"
    ) -> bool:
        """React to the triggering note via GitLab's award-emoji API.

        :returns: ``False`` (never raises) for a Gitea-backed instance, or
            an ``external_id`` this adapter didn't mint.
        """
        if self._is_gitea:
            return False
        parsed = _parse_note_external_id(feedback.external_id)
        if parsed is None:
            return False
        repo, mr_iid, note_id = parsed
        try:
            await self._request(
                "POST",
                f"/projects/{self._pid(repo)}/merge_requests/{mr_iid}"
                f"/notes/{note_id}/award_emoji",
                json={"name": token},
            )
            return True
        except Exception:  # noqa: BLE001 — best-effort acknowledgment
            return False

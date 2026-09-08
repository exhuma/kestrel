"""Async GitHub REST client (coded to the public API docs).

Also hosts the GitHub adapters for the feature-003 ``TaskSource`` / ``CodeHost``
ports: GitHub implements both roles over a single repository, keyed by the
source-neutral ``task_ref`` ``"owner/name#123"``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx

from app.ports import ChangeRequest, Feedback
from app.services import github_reviews
from app.services.exceptions import GitHubError
from app.services.feedback.timeparse import parse_iso

#: Extracts a PR/MR number from the tail of a change-request URL —
#: GitHub's ``.../pull/123`` or GitLab's ``.../merge_requests/123``.
_CR_NUMBER_RE = re.compile(r"/(?:pull|merge_requests)/(\d+)(?:[/?#]|$)")


def change_request_number(url: str) -> int | None:
    """
    Extract a pull/merge-request number from an existing ``run.pr_url``.

    Used to backfill ``pr_number``-less rows persisted before that column
    existed, with no migration data-fix (data-model.md). Never raises.

    :param url: A change-request URL, or ``""``/``None``/anything malformed.
    :returns: The trailing number, or ``None`` when ``url`` doesn't match.
    """
    if not url:
        return None
    match = _CR_NUMBER_RE.search(url)
    return int(match.group(1)) if match else None


def parse_github_ref(ref: str) -> tuple[str, int]:
    """
    Split a GitHub ``task_ref`` ``"owner/name#123"`` into ``(repo, number)``.

    :param ref: The source-native ticket id.
    :returns: ``(owner/name, issue_number)``.
    :raises ValueError: If the ref is not ``owner/name#<int>``.
    """
    repo, _, num = ref.rpartition("#")
    if not repo or not num.isdigit():
        raise ValueError(f"not a GitHub task_ref: {ref!r}")
    return repo, int(num)


@dataclass
class Issue:
    """A GitHub issue, trimmed to what the workflow needs."""

    number: int
    title: str
    body: str


class GitHubClient:
    """Thin async wrapper over the GitHub REST API."""

    def __init__(
        self, base_url: str, token: str, verify: bool = True
    ) -> None:
        """
        :param base_url: API base, e.g. https://api.github.com.
        :param token: Bearer token for the Authorization header.
        :param verify: Verify TLS certificates (``False`` for a self-hosted
            GitHub Enterprise with an untrusted CA).
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http = httpx.AsyncClient(base_url=self.base_url, verify=verify)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # Only authenticate when a token is configured. Sending an empty
        # "Bearer " is an illegal header value (httpx raises
        # LocalProtocolError before the request is even sent); omitting
        # it instead falls back to unauthenticated access, which works
        # for public-repo reads and yields a clean 401/403 for anything
        # that genuinely needs a token.
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _request(self, method: str, path: str, **kw) -> httpx.Response:
        resp = await self._http.request(
            method, path, headers=self._headers(), **kw
        )
        if resp.status_code >= 300:
            raise GitHubError(
                f"{method} {path} -> {resp.status_code}: {resp.text}"
                f"{self._auth_hint(resp.status_code)}"
            )
        return resp

    def _auth_hint(self, status_code: int) -> str:
        """A human hint for the auth-shaped failures (401/403/404).

        GitHub returns 404 (not 403) for a private repo the caller can't
        see, so a 404 is ambiguous between "no access" and "does not
        exist". Point at the most likely cause given whether we sent a
        token at all.
        """
        if status_code not in (401, 403, 404):
            return ""
        if not self.token:
            return (
                " — no GitHub token is configured, so this request was "
                "unauthenticated. Set KESTREL_GITHUB_TOKEN and make sure "
                "your .env is in the backend working directory."
            )
        return (
            " — the configured token may lack access to this repo "
            "(a fine-grained PAT must grant it Contents, Issues, and "
            "Pull requests), or the repo/resource does not exist."
        )

    async def check_health(self) -> bool:
        """Best-effort reachability + auth probe (feature 014).

        A single cheap, repo-independent, authenticated call. Never
        raises: any failure (network, auth, timeout, malformed response)
        is caught and reported as ``False``.
        """
        try:
            await self._request("GET", "/user")
        except Exception:  # noqa: BLE001 — health checks never raise
            return False
        return True

    async def get_issue(self, repo: str, number: int) -> Issue:
        """Fetch an issue by number."""
        resp = await self._request("GET", f"/repos/{repo}/issues/{number}")
        data = resp.json()
        return Issue(
            number=data["number"],
            title=data.get("title", ""),
            body=data.get("body") or "",
        )

    async def create_issue_comment(
        self, repo: str, number: int, body: str
    ) -> str:
        """Post a comment on an issue and return its html_url."""
        resp = await self._request(
            "POST",
            f"/repos/{repo}/issues/{number}/comments",
            json={"body": body},
        )
        return resp.json()["html_url"]

    async def list_issues_by_label(
        self, repo: str, label: str, *, state: str = "open"
    ) -> list[Issue]:
        """
        List issues carrying ``label``, following pagination.

        The issues API also returns pull requests; those (items with a
        ``pull_request`` key) are excluded so only real issues are returned.
        """
        issues: list[Issue] = []
        resp = await self._request(
            "GET",
            f"/repos/{repo}/issues",
            params={"labels": label, "state": state, "per_page": 100},
        )
        while True:
            for item in resp.json():
                if "pull_request" in item:
                    continue
                issues.append(
                    Issue(
                        number=item["number"],
                        title=item.get("title", ""),
                        body=item.get("body") or "",
                    )
                )
            nxt = resp.links.get("next")
            if not nxt:
                return issues
            resp = await self._request("GET", nxt["url"])

    async def get_default_branch(self, repo: str) -> str:
        """Return the repo's default branch (PR base)."""
        resp = await self._request("GET", f"/repos/{repo}")
        return resp.json()["default_branch"]

    async def update_issue(self, repo: str, number: int, body: str) -> None:
        """Replace an issue's body."""
        await self._request(
            "PATCH", f"/repos/{repo}/issues/{number}", json={"body": body}
        )

    async def add_label(self, repo: str, number: int, label: str) -> None:
        """Add ``label`` to an issue (a no-op if ``label`` is empty)."""
        if not label:
            return
        await self._request(
            "POST",
            f"/repos/{repo}/issues/{number}/labels",
            json={"labels": [label]},
        )

    async def remove_label(self, repo: str, number: int, label: str) -> None:
        """Remove ``label`` from an issue (idempotent; empty is a no-op).

        A 404 (label already absent) is treated as success, not an error
        — removing an already-removed label is the expected steady state
        once a run has already transitioned past it.
        """
        if not label:
            return
        resp = await self._http.request(
            "DELETE",
            f"/repos/{repo}/issues/{number}/labels/{quote(label, safe='')}",
            headers=self._headers(),
        )
        if resp.status_code >= 300 and resp.status_code != 404:
            raise GitHubError(
                f"DELETE labels/{label} -> {resp.status_code}: {resp.text}"
            )

    async def create_issue(self, repo: str, title: str, body: str) -> int:
        """Create a new issue (no labels); return its number.

        Never applies any label — in particular, never the configured
        trigger label — so a caller creating a follow-up task (feature
        012) never causes it to satisfy the webhook/reconcile trigger
        condition as a side effect of creation.
        """
        resp = await self._request(
            "POST",
            f"/repos/{repo}/issues",
            json={"title": title, "body": body},
        )
        return resp.json()["number"]

    async def list_issue_comments(
        self, repo: str, number: int, since: str | None = None
    ) -> list[dict]:
        """
        List an issue's comments, oldest first, following pagination.

        :param since: GitHub's own ``since=`` filter (an ISO-8601
            timestamp); server-side only — callers still filter for exact
            cursor exclusivity themselves (feature 013).
        """
        comments: list[dict] = []
        params: dict[str, object] = {"per_page": 100}
        if since:
            params["since"] = since
        resp = await self._request(
            "GET", f"/repos/{repo}/issues/{number}/comments", params=params
        )
        while True:
            comments.extend(resp.json())
            nxt = resp.links.get("next")
            if not nxt:
                return comments
            resp = await self._request("GET", nxt["url"])

    async def add_issue_comment_reaction(
        self, repo: str, comment_id: int, content: str
    ) -> None:
        """React to an issue comment (feature 013 acknowledgment, R8)."""
        await self._request(
            "POST",
            f"/repos/{repo}/issues/comments/{comment_id}/reactions",
            json={"content": content},
        )

    async def get_pull_request(self, repo: str, number: int) -> dict:
        """Fetch a pull request's raw payload (state/merged/html_url)."""
        resp = await self._request("GET", f"/repos/{repo}/pulls/{number}")
        return resp.json()

    async def list_pull_reviews(self, repo: str, number: int) -> list[dict]:
        """List a pull request's reviews, oldest first, following pagination.

        No server-side ``since`` filter exists for this endpoint; callers
        filter client-side for cursor exclusivity.
        """
        reviews: list[dict] = []
        resp = await self._request(
            "GET", f"/repos/{repo}/pulls/{number}/reviews",
            params={"per_page": 100},
        )
        while True:
            reviews.extend(resp.json())
            nxt = resp.links.get("next")
            if not nxt:
                return reviews
            resp = await self._request("GET", nxt["url"])

    async def list_pull_review_comments(
        self, repo: str, number: int, since: str | None = None
    ) -> list[dict]:
        """List a pull request's inline review comments, oldest first.

        :param since: GitHub's own ``since=`` filter (an ISO-8601
            timestamp); server-side only — callers still filter for exact
            cursor exclusivity themselves (feature 013).
        """
        comments: list[dict] = []
        params: dict[str, object] = {"per_page": 100}
        if since:
            params["since"] = since
        resp = await self._request(
            "GET", f"/repos/{repo}/pulls/{number}/comments", params=params
        )
        while True:
            comments.extend(resp.json())
            nxt = resp.links.get("next")
            if not nxt:
                return comments
            resp = await self._request("GET", nxt["url"])

    async def add_pull_review_comment_reaction(
        self, repo: str, comment_id: int, content: str
    ) -> None:
        """React to an inline review comment (feature 013 acknowledgment)."""
        await self._request(
            "POST",
            f"/repos/{repo}/pulls/comments/{comment_id}/reactions",
            json={"content": content},
        )

    async def create_pull_request(
        self,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
        draft: bool = True,
    ) -> str:
        """Open a pull request and return its html_url."""
        resp = await self._request(
            "POST",
            f"/repos/{repo}/pulls",
            json={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
            },
        )
        return resp.json()["html_url"]


class GitHubCodeHost:
    """``CodeHost`` adapter over :class:`GitHubClient` (pull requests)."""

    def __init__(self, client: GitHubClient, git_base: str) -> None:
        self._client = client
        self._git_base = git_base.rstrip("/")

    async def get_default_branch(self, repo: str) -> str:
        return await self._client.get_default_branch(repo)

    async def check_health(self) -> bool:
        """Delegates to the shared client — same connection/credential
        as this profile's task source, when GitHub plays both roles."""
        return await self._client.check_health()

    def clone_remote(self, repo: str) -> str:
        return f"{self._git_base}/{repo}.git"

    def git_credential(self) -> tuple[str, str]:
        return ("x-access-token", self._client.token)

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
        return await self._client.create_pull_request(
            repo, head=head, base=base, title=title, body=body, draft=draft
        )

    async def get_change_request(
        self, repo: str, number: int
    ) -> ChangeRequest:
        """Fetch a pull request's lifecycle state (feature 013, US3/US4)."""
        data = await self._client.get_pull_request(repo, number)
        if data.get("merged"):
            state: Literal["open", "merged", "closed"] = "merged"
        elif data.get("state") == "closed":
            state = "closed"
        else:
            state = "open"
        return ChangeRequest(
            number=number, state=state, url=data.get("html_url") or ""
        )

    async def list_review_comments(
        self, repo: str, number: int, since: str | None = None
    ) -> list[Feedback]:
        """Every reviewer-authored signal on the PR (feature 013, US3).

        Merges PR-conversation comments (the issues endpoint, since a
        pull request *is* an issue), review summaries, and inline review
        comments — see :mod:`app.services.github_reviews`.
        """
        conversation = await self._client.list_issue_comments(
            repo, number, since=since
        )
        reviews = await self._client.list_pull_reviews(repo, number)
        review_comments = await self._client.list_pull_review_comments(
            repo, number, since=since
        )
        cutoff = parse_iso(since) if since else None
        return github_reviews.merge_review_feedback(
            repo, conversation, reviews, review_comments, cutoff
        )

    async def acknowledge(
        self, feedback: Feedback, token: str = "eyes"
    ) -> bool:
        """React to the triggering review comment (feature 013, US3)."""
        parsed = github_reviews.parse_review_external_id(feedback.external_id)
        if parsed is None:
            return False
        kind, repo, comment_id = parsed
        try:
            if kind == "comment":
                await self._client.add_issue_comment_reaction(
                    repo, comment_id, token
                )
            else:
                await self._client.add_pull_review_comment_reaction(
                    repo, comment_id, token
                )
            return True
        except Exception:  # noqa: BLE001 — best-effort acknowledgment
            return False



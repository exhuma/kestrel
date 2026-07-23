"""Async GitHub REST client (coded to the public API docs).

Also hosts the GitHub adapters for the feature-003 ``TaskSource`` / ``CodeHost``
ports: GitHub implements both roles over a single repository, keyed by the
source-neutral ``task_ref`` ``"owner/name#123"``.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.ports import Task
from app.services.exceptions import GitHubError
from app.services.workflow_text import append_sentinel


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


class GitHubTaskSource:
    """``TaskSource`` adapter over :class:`GitHubClient` (issues)."""

    def __init__(self, client: GitHubClient, public_base_url: str = "") -> None:
        self._client = client
        self._public_base_url = public_base_url.rstrip("/")

    async def get_task(self, ref: str) -> Task:
        repo, number = parse_github_ref(ref)
        issue = await self._client.get_issue(repo, number)
        return Task(ref=ref, title=issue.title, body=issue.body)

    async def post_comment(self, ref: str, body: str) -> str:
        repo, number = parse_github_ref(ref)
        return await self._client.create_issue_comment(repo, number, body)

    async def attach(self, ref: str, name: str, content: str) -> None:
        """No-op: GitHub issues have no attachment API; PRD goes in the body."""
        return None

    async def publish_refined(self, ref: str, content: str) -> None:
        """Write the approved PRD back to the issue body with the sentinel."""
        repo, number = parse_github_ref(ref)
        await self._client.update_issue(repo, number, append_sentinel(content))

    def deep_link_ref(self, ref: str) -> str:
        repo, number = parse_github_ref(ref)
        return f"https://github.com/{repo}/issues/{number}"


class GitHubCodeHost:
    """``CodeHost`` adapter over :class:`GitHubClient` (pull requests)."""

    def __init__(self, client: GitHubClient, git_base: str) -> None:
        self._client = client
        self._git_base = git_base.rstrip("/")

    async def get_default_branch(self, repo: str) -> str:
        return await self._client.get_default_branch(repo)

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

"""Async GitHub REST client (coded to the public API docs)."""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.services.exceptions import GitHubError


@dataclass
class Issue:
    """A GitHub issue, trimmed to what the workflow needs."""

    number: int
    title: str
    body: str


class GitHubClient:
    """Thin async wrapper over the GitHub REST API."""

    def __init__(self, base_url: str, token: str) -> None:
        """
        :param base_url: API base, e.g. https://api.github.com.
        :param token: Bearer token for the Authorization header.
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http = httpx.AsyncClient(base_url=self.base_url)

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

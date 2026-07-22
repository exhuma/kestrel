"""Async GitLab REST client + ``CodeHost`` adapter (feature 003).

The self-hostable code host for Jira-resolved repositories: kestrel is sovereign
by design, so a resolved repo can live on an on-prem GitLab and open a **merge
request** there. Gitea/Forgejo is the same port with different endpoints.
"""
from __future__ import annotations

from urllib.parse import quote

import httpx

from app.services.exceptions import GitError


class GitLabError(GitError):
    """A GitLab REST call failed."""


class GitLabCodeHost:
    """``CodeHost`` over the GitLab REST API (merge requests).

    :param base_url: Instance base URL, e.g. ``https://gitlab.internal``.
    :param token: Personal access token (sent as ``PRIVATE-TOKEN``; never
        logged).
    """

    def __init__(self, base_url: str, token: str) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._http = httpx.AsyncClient(base_url=f"{self._base}/api/v4")

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
        """Return the project's default branch (also the reachability probe)."""
        resp = await self._request("GET", f"/projects/{self._pid(repo)}")
        return resp.json()["default_branch"]

    def clone_remote(self, repo: str) -> str:
        """The HTTPS git remote a worktree clones/fetches from."""
        return f"{self._base}/{repo}.git"

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

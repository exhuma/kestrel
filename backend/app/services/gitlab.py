"""Async GitLab REST client + ``CodeHost`` adapter (feature 003).

The self-hostable code host for Jira-resolved repositories: kestrel is sovereign
by design, so a resolved repo can live on an on-prem GitLab and open a **merge
request** there. Gitea/Forgejo is the same port with different endpoints.
"""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote

import httpx

from app.document_formats.markdown import render_markdown
from app.documents import Document
from app.ports import ChangeRequest, RequiredCiStatus
from app.services.ci_status import gitlab_status
from app.services.exceptions import GitError

#: GitLab's own three MR states, mapped 1:1 onto ``ChangeRequest.state``
#: ("opened" is GitLab's spelling; the port uses "open" everywhere else).
_STATE_MAP: dict[str, Literal["open", "merged", "closed"]] = {
    "opened": "open", "merged": "merged", "closed": "closed",
}


class GitLabError(GitError):
    """A GitLab REST call failed."""


class GitLabCodeHost:
    """``CodeHost`` over the GitLab REST API (merge requests).

    :param base_url: Instance base URL, e.g. ``https://gitlab.internal``.
    :param token: Personal access token (sent as ``PRIVATE-TOKEN``; never
        logged).
    """

    def __init__(
        self, base_url: str, token: str, verify: bool = True
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
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

    def supports_change_requests(self) -> bool:
        """Report GitLab and Gitea merge-request support."""
        return True

    async def check_health(self) -> bool:
        """Best-effort reachability + auth probe (feature 014).

        A single cheap, project-independent, authenticated call — same
        endpoint shape for a real GitLab instance and a Gitea instance
        (this adapter already assumes GitLab-API-compatible endpoints for
        both, e.g. ``get_default_branch``).

        :raises httpx.HTTPError: When the host cannot be reached; the
            health service logs why.
        :raises GitLabError: When it answers with a failure (e.g. 401).
        """
        await self._request("GET", "/user")
        return True

    def clone_remote(self, repo: str) -> str:
        """The HTTPS git remote a worktree clones/fetches from."""
        return f"{self._base}/{repo}.git"

    def file_url(self, repo: str, branch: str, path: str) -> str:
        """The raw content of *path* on *branch* (feature 043)."""
        return f"{self._base}/{repo}/-/raw/{quote(branch)}/{quote(path)}"

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
        body: Document,
        draft: bool = True,
    ) -> str:
        """Open a merge request and return its ``web_url``.

        GitLab signals a draft MR with a ``Draft:`` title prefix.
        """
        mr_title = f"Draft: {title}" if draft else title
        description = render_markdown(body)
        resp = await self._request(
            "POST",
            f"/projects/{self._pid(repo)}/merge_requests",
            json={
                "source_branch": head,
                "target_branch": base,
                "title": mr_title,
                "description": description,
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

    async def required_ci_statuses(
        self, repo: str, number: int, names: list[str]
    ) -> list[RequiredCiStatus]:
        """Normalize requested GitLab pipeline-job states for an MR."""
        path = f"/projects/{self._pid(repo)}/merge_requests/{number}/pipelines"
        pipelines = (await self._request("GET", path)).json()
        if not pipelines:
            return [RequiredCiStatus(name, "pending") for name in names]
        pipeline_id = pipelines[0]["id"]
        jobs = await self._list_pages(
            f"/projects/{self._pid(repo)}/pipelines/{pipeline_id}/jobs"
        )
        by_name = {job.get("name"): job for job in jobs}
        return [gitlab_status(name, by_name.get(name)) for name in names]

    async def _list_pages(self, path: str) -> list[dict]:
        """Read every ascending GitLab page at ``path``."""
        page = 1
        items: list[dict] = []
        while True:
            resp = await self._request(
                "GET", path,
                params={
                    "order_by": "created_at", "sort": "asc",
                    "per_page": 100, "page": page,
                },
            )
            items.extend(resp.json())
            next_page = resp.headers.get("x-next-page")
            if not next_page:
                return items
            page = int(next_page)

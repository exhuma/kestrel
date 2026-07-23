"""Async Jira REST client + ``TaskSource`` adapter (feature 003).

Jira is a *task source* whose code lives in a separate repository. This client
reuses ``httpx`` (no new dependency) and targets the REST **v2** API, whose
plain-text comment/description bodies keep the integration simple and work on
self-hosted Jira Server/DC — the sovereignty target. Auth is configurable:
``basic`` (Cloud — email + API token) or ``bearer`` (Server/DC — PAT). The
token is a secret and is never logged.
"""
from __future__ import annotations

import httpx

from app.ports import Task
from app.services.exceptions import GitError


class JiraError(GitError):
    """A Jira REST call failed."""


class JiraClient:
    """Thin async wrapper over the Jira REST v2 API."""

    def __init__(
        self,
        base_url: str,
        *,
        auth: str = "basic",
        email: str = "",
        token: str = "",
    ) -> None:
        self._base = base_url.rstrip("/")
        self._auth_mode = auth
        self._email = email
        self._token = token
        http_auth = (
            httpx.BasicAuth(email, token)
            if auth == "basic" and token
            else None
        )
        self._http = httpx.AsyncClient(
            base_url=f"{self._base}/rest/api/2", auth=http_auth
        )

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._auth_mode == "bearer" and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if extra:
            headers.update(extra)
        return headers

    async def _request(self, method: str, path: str, **kw) -> httpx.Response:
        headers = kw.pop("headers", None) or self._headers()
        resp = await self._http.request(method, path, headers=headers, **kw)
        if resp.status_code >= 300:
            # Redact: neither the token nor Basic credentials are echoed.
            raise JiraError(
                f"{method} {path} -> {resp.status_code}: {resp.text}"
            )
        return resp

    @staticmethod
    def _to_task(issue: dict) -> Task:
        fields = issue.get("fields") or {}
        return Task(
            ref=issue["key"],
            title=fields.get("summary") or "",
            body=fields.get("description") or "",
        )

    async def search(
        self, jql: str, *, fields: list[str], max_results: int = 50
    ) -> list[Task]:
        """Return the qualifying issues for ``jql`` as ``Task``s.

        Uses the enhanced ``/search/jql`` endpoint (Jira Cloud removed the
        legacy ``/search``). Pagination is token-based: the old ``startAt``/
        ``total`` model is gone, so every page is followed via
        ``nextPageToken`` until the response reports ``isLast``. Collecting
        every page keeps the poll's dismissal-clear logic correct.
        """
        body = {"jql": jql, "fields": fields, "maxResults": max_results}
        issues: list[dict] = []
        token: str | None = None
        while True:
            page = await self._search_page(body, token)
            issues.extend(page.get("issues", []))
            token = None if page.get("isLast") else page.get("nextPageToken")
            if not token:
                break
        return [self._to_task(i) for i in issues]

    async def _search_page(
        self, body: dict, token: str | None
    ) -> dict:
        """POST one enhanced-search page; ``token`` continues a prior page."""
        payload = body if token is None else {**body, "nextPageToken": token}
        resp = await self._request("POST", "/search/jql", json=payload)
        return resp.json()

    async def get_issue(self, key: str) -> Task:
        """Fetch a single issue's summary/description."""
        resp = await self._request(
            "GET", f"/issue/{key}", params={"fields": "summary,description"}
        )
        return self._to_task(resp.json())

    async def get_field(self, key: str, field: str) -> str | None:
        """Read one field's scalar value (the repo-resolution field)."""
        resp = await self._request(
            "GET", f"/issue/{key}", params={"fields": field}
        )
        value = (resp.json().get("fields") or {}).get(field)
        if value is None:
            return None
        return value if isinstance(value, str) else str(value)

    async def get_remote_links(self, key: str) -> list[dict]:
        """Return the issue's remote/web links (raw ``object.url``/title)."""
        resp = await self._request("GET", f"/issue/{key}/remotelink")
        data = resp.json()
        return data if isinstance(data, list) else []

    async def add_comment(self, key: str, body: str) -> str:
        """Post a comment; return its API URL."""
        resp = await self._request(
            "POST", f"/issue/{key}/comment", json={"body": body}
        )
        return resp.json().get("self", "")

    async def add_attachment(self, key: str, name: str, content: str) -> None:
        """Attach a file to the issue (the PRD). Requires the XSRF header."""
        await self._request(
            "POST",
            f"/issue/{key}/attachments",
            headers=self._headers({"X-Atlassian-Token": "no-check"}),
            files={"file": (name, content.encode("utf-8"), "text/markdown")},
        )


class JiraTaskSource:
    """``TaskSource`` adapter over :class:`JiraClient` (RFC tickets)."""

    def __init__(self, client: JiraClient, public_base_url: str = "") -> None:
        self._client = client
        self._base = client._base

    async def get_task(self, ref: str) -> Task:
        return await self._client.get_issue(ref)

    async def post_comment(self, ref: str, body: str) -> str:
        return await self._client.add_comment(ref, body)

    async def attach(self, ref: str, name: str, content: str) -> None:
        await self._client.add_attachment(ref, name, content)

    async def publish_refined(self, ref: str, content: str) -> None:
        """Deliver the approved PRD as an attachment on the RFC (FR-011)."""
        await self._client.add_attachment(ref, "PRD.md", content)

    def deep_link_ref(self, ref: str) -> str:
        return f"{self._base}/browse/{ref}"

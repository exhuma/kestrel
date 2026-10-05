"""Async Jira REST client (feature 003; split out of ``jira.py``, 046).

Targets REST v3 with ADF for Cloud, or v2 for self-hosted Jira Server/DC.
Documents cross this boundary in Jira's own format only here: comments
and descriptions are rendered straight from a ``Document`` (ADF on
Cloud), and issue descriptions are parsed into one (constitution
Principle VI). Auth is ``basic`` (Cloud: email + API token) or ``bearer``
(Server/DC: PAT). The token is a secret and is never logged.
"""

from __future__ import annotations

import httpx

from app.document_formats.adf import parse_adf, render_adf
from app.document_formats.markdown import render_markdown
from app.documents import Document
from app.ports import Person, Task
from app.services.exceptions import GitError

#: The first HTTP status that is not a success.
_FIRST_FAILURE_STATUS = 300


class JiraError(GitError):
    """A Jira REST call failed."""


def person(raw: object) -> Person | None:
    """A Jira user object as a :class:`Person`, or ``None``.

    Cloud identifies users by ``accountId``; Server/DC by ``name`` (or
    ``key``).
    """
    if not isinstance(raw, dict):
        return None
    account = raw.get("accountId") or raw.get("name") or raw.get("key")
    if not account:
        return None
    return Person(str(account), str(raw.get("displayName") or ""))


class JiraClient:
    """Thin async wrapper over the configured Jira REST API deployment."""

    def __init__(
        self,
        base_url: str,
        **options: str | bool,
    ) -> None:
        auth = str(options.get("auth", "basic"))
        email = str(options.get("email", ""))
        token = str(options.get("token", ""))
        verify = bool(options.get("verify", True))
        deployment = options.get("deployment", "server")
        self._base = base_url.rstrip("/")
        self._auth_mode = auth
        self._email = email
        self._token = token
        self._cloud = deployment == "cloud"
        http_auth = (
            httpx.BasicAuth(email, token) if auth == "basic" and token else None
        )
        self._http = httpx.AsyncClient(
            base_url=f"{self._base}/rest/api/{'3' if self._cloud else '2'}",
            auth=http_auth,
            verify=verify,
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
        if resp.status_code >= _FIRST_FAILURE_STATUS:
            # Redact: neither the token nor Basic credentials are echoed.
            raise JiraError(
                f"{method} {path} -> {resp.status_code}: {resp.text}"
            )
        return resp

    def _render(self, body: Document) -> object:
        """A document as this deployment's body format."""
        return render_adf(body) if self._cloud else render_markdown(body)

    async def check_health(self) -> bool:
        """Best-effort reachability + auth probe (feature 014).

        A single cheap, issue-independent, authenticated call. Never
        raises: any failure (network, auth, timeout, malformed response)
        is caught and reported as ``False``.
        """
        try:
            await self._request("GET", "/myself")
        except (httpx.HTTPError, JiraError):
            return False
        return True

    @staticmethod
    def _to_task(issue: dict, change_owner_field: str = "") -> Task:
        fields = issue.get("fields") or {}
        return Task(
            ref=issue["key"],
            title=fields.get("summary") or "",
            body=parse_adf(fields.get("description")),
            reporter=person(fields.get("reporter")),
            change_owner=(
                person(fields.get(change_owner_field))
                if change_owner_field else None
            ),
        )

    async def search(
        self, jql: str, *, fields: list[str], max_results: int = 50
    ) -> list[Task]:
        """Return the qualifying issues for ``jql`` as ``Task``s.

        Cloud uses enhanced ``/search/jql`` token pagination. Server/DC keeps
        the v2 ``/search`` ``startAt``/``total`` page model. Collecting every
        page keeps the poll's dismissal-clear logic correct.
        """
        body = {"jql": jql, "fields": fields, "maxResults": max_results}
        if self._cloud:
            return await self._search_cloud(body)
        return await self._search_server(body)

    async def _search_cloud(self, body: dict) -> list[Task]:
        """Collect all Cloud enhanced-search pages into source-neutral tasks."""
        issues: list[dict] = []
        token: str | None = None
        while True:
            page = await self._search_cloud_page(body, token)
            issues.extend(page.get("issues", []))
            token = None if page.get("isLast") else page.get("nextPageToken")
            if not token:
                break
        return [self._to_task(i) for i in issues]

    async def _search_cloud_page(self, body: dict, token: str | None) -> dict:
        """POST one Cloud enhanced-search page, continuing with ``token``."""
        payload = body if token is None else {**body, "nextPageToken": token}
        resp = await self._request("POST", "/search/jql", json=payload)
        return resp.json()

    async def _search_server(self, body: dict) -> list[Task]:
        """Collect all Jira Server/DC v2 offset-search pages into tasks."""
        issues: list[dict] = []
        start = 0
        while True:
            page = await self._search_server_page(body, start)
            page_issues = page.get("issues", [])
            issues.extend(page_issues)
            start += len(page_issues)
            if not page_issues or start >= page.get("total", start):
                return [self._to_task(issue) for issue in issues]

    async def _search_server_page(self, body: dict, start: int) -> dict:
        """POST one Jira Server/DC v2 search page at the requested offset."""
        payload = {**body, "startAt": start}
        resp = await self._request("POST", "/search", json=payload)
        return resp.json()

    async def get_issue(self, key: str, change_owner_field: str = "") -> Task:
        """Fetch one issue: summary, description, reporter, change owner."""
        fields = ["summary", "description", "reporter"]
        if change_owner_field:
            fields.append(change_owner_field)
        resp = await self._request(
            "GET", f"/issue/{key}", params={"fields": ",".join(fields)}
        )
        return self._to_task(resp.json(), change_owner_field)

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

    async def add_comment(self, key: str, body: Document) -> str:
        """Post a comment; return its API URL."""
        resp = await self._request(
            "POST", f"/issue/{key}/comment", json={"body": self._render(body)}
        )
        return resp.json().get("self", "")

    async def delete_resource(self, path: str) -> None:
        """Delete an absolute Jira resource URL, ignoring a missing resource."""
        try:
            await self._request("DELETE", path)
        except JiraError as exc:
            if "-> 404:" not in str(exc):
                raise

    async def delete_issue(self, key: str) -> None:
        """Delete a Kestrel-created issue, treating an absent issue as clean."""
        await self.delete_resource(f"/issue/{key}")

    async def add_attachment(
        self, key: str, name: str, data: bytes, mimetype: str
    ) -> None:
        """Attach a binary file to the issue. Requires the XSRF header."""
        await self._request(
            "POST",
            f"/issue/{key}/attachments",
            headers=self._headers({"X-Atlassian-Token": "no-check"}),
            files={"file": (name, data, mimetype)},
        )

    async def create_subtask(
        self,
        parent_key: str,
        project_key: str,
        summary: str,
        body: Document,
        extra_fields: dict[str, object] | None = None,
    ) -> str:
        """Create a native Sub-task issue linked to ``parent_key``.

        Jira's own subdivision primitive (distinct from a plain linked
        issue), so the parent/child relationship is native, not just a
        body reference.
        """
        fields = {
            "project": {"key": project_key},
            "summary": summary,
            "description": self._render(body),
            "issuetype": {"name": "Sub-task"},
            "parent": {"key": parent_key},
        }
        if extra_fields:
            fields.update(extra_fields)
        resp = await self._request("POST", "/issue", json={"fields": fields})
        return resp.json()["key"]

    async def add_remote_link(self, key: str, url: str, title: str) -> None:
        """Add a titled web link to an issue for repository resolution."""
        await self._request(
            "POST",
            f"/issue/{key}/remotelink",
            json={"object": {"url": url, "title": title}},
        )

    async def transition_issue(self, key: str, transition_id: str) -> None:
        """Apply a configured workflow transition (feature 006).

        Sub-tasks kestrel created only (constitution, fourth access-model
        constraint).
        """
        await self._request(
            "POST",
            f"/issue/{key}/transitions",
            json={"transition": {"id": transition_id}},
        )

    async def set_field(self, key: str, field: str, value: object) -> None:
        """Write one field's value (e.g. a time-tracking field)."""
        await self._request(
            "PUT", f"/issue/{key}", json={"fields": {field: value}}
        )

    async def list_comments(self, key: str) -> list[dict]:
        """Fetch every comment on an issue, oldest first.

        Paginates via ``startAt``/``total`` until every page has been read;
        typical RFC comment volume makes this one or two calls.
        """
        comments: list[dict] = []
        start = 0
        while True:
            resp = await self._request(
                "GET",
                f"/issue/{key}/comment",
                params={"orderBy": "created", "startAt": start},
            )
            data = resp.json()
            page = data.get("comments", [])
            comments.extend(page)
            start += len(page)
            if not page or start >= data.get("total", start):
                return comments

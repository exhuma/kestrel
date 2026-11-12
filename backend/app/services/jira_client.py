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
        #: The account behind the token, read once (#99).
        self._myself: Person | None = None
        http_auth = (
            httpx.BasicAuth(email, token) if auth == "basic" and token else None
        )
        self._http = httpx.AsyncClient(
            base_url=f"{self._base}/rest/api/{'3' if self._cloud else '2'}",
            auth=http_auth,
            verify=verify,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._auth_mode == "bearer" and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _request(self, method: str, path: str, **kw) -> httpx.Response:
        headers = {**self._headers(), **kw.pop("headers", {})}
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
        """Reachability + auth probe (feature 014): one cheap,
        issue-independent, authenticated call.

        :raises httpx.HTTPError: When Jira cannot be reached (DNS, TLS,
            proxy, timeout) — the health service logs why.
        :raises JiraError: When Jira answers with a failure (e.g. 401).
        """
        await self._request("GET", "/myself")
        return True

    async def myself(self) -> Person | None:
        """The account behind this client's token: kestrel's account
        (#99). Read once, then kept for the life of the client.

        :returns: ``None`` when Jira names no account for it.
        """
        if self._myself is None:
            resp = await self._request("GET", "/myself")
            self._myself = person(resp.json())
        return self._myself

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
        page keeps the poll's view of the qualifying set complete.
        """
        issues = await self.search_issues(
            jql, fields=fields, max_results=max_results
        )
        return [self._to_task(issue) for issue in issues]

    async def search_issues(
        self, jql: str, *, fields: list[str], max_results: int = 50
    ) -> list[dict]:
        """Every issue ``jql`` finds, as Jira returns it, with *fields*:
        for a caller that needs fields a ``Task`` does not carry."""
        body = {"jql": jql, "fields": fields, "maxResults": max_results}
        if self._cloud:
            return await self._search_cloud(body)
        return await self._search_server(body)

    async def _search_cloud(self, body: dict) -> list[dict]:
        """Collect all Cloud enhanced-search pages into source-neutral tasks."""
        issues: list[dict] = []
        token: str | None = None
        while True:
            page = await self._search_cloud_page(body, token)
            issues.extend(page.get("issues", []))
            token = None if page.get("isLast") else page.get("nextPageToken")
            if not token:
                return issues

    async def _search_cloud_page(self, body: dict, token: str | None) -> dict:
        """POST one Cloud enhanced-search page, continuing with ``token``."""
        payload = body if token is None else {**body, "nextPageToken": token}
        resp = await self._request("POST", "/search/jql", json=payload)
        return resp.json()

    async def _search_server(self, body: dict) -> list[dict]:
        """Collect all Jira Server/DC v2 offset-search pages into tasks."""
        issues: list[dict] = []
        start = 0
        while True:
            page = await self._search_server_page(body, start)
            page_issues = page.get("issues", [])
            issues.extend(page_issues)
            start += len(page_issues)
            if not page_issues or start >= page.get("total", start):
                return issues

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

    async def create_issue(
        self, fields: dict[str, object], body: Document
    ) -> str:
        """Create an issue from Jira *fields* plus a description; return
        its key. Callers name the project, type, summary and any parent."""
        payload = {**fields, "description": self._render(body)}
        resp = await self._request("POST", "/issue", json={"fields": payload})
        return resp.json()["key"]

    async def find_by_label(self, label: str) -> str | None:
        """The key of an issue carrying *label*, or ``None``."""
        body = {"jql": f'labels = "{label}"', "fields": ["summary"],
                "maxResults": 1}
        path = "/search/jql" if self._cloud else "/search"
        resp = await self._request("POST", path, json=body)
        issues = resp.json().get("issues") or []
        return str(issues[0]["key"]) if issues else None

    async def link_issues(
        self, link_type: str, outward_key: str, inward_key: str
    ) -> None:
        """Link two issues so that *outward_key* reads with the link
        type's outward description ("blocks") towards *inward_key*.

        Jira's REST names the two ends the other way round: the issue
        given as ``inwardIssue`` is the one the outward description
        applies to.
        """
        await self._request(
            "POST", "/issueLink",
            json={
                "type": {"name": link_type},
                "inwardIssue": {"key": outward_key},
                "outwardIssue": {"key": inward_key},
            },
        )

    async def attach_markdown(
        self, key: str, name: str, document: Document
    ) -> str:
        """Attach *document* to the issue as a Markdown file; return its
        content URL. Jira refuses an upload without the XSRF opt-out
        header."""
        data = render_markdown(document).encode("utf-8")
        resp = await self._request(
            "POST", f"/issue/{key}/attachments",
            headers={"X-Atlassian-Token": "no-check"},
            files={"file": (name, data, "text/markdown")},
        )
        uploaded = resp.json()
        first = uploaded[0] if isinstance(uploaded, list) and uploaded else {}
        return str(first.get("content") or first.get("self") or "")

    async def link_type_names(self) -> set[str]:
        """The names of the issue link types this Jira has."""
        resp = await self._request("GET", "/issueLinkType")
        types = resp.json().get("issueLinkTypes") or []
        return {str(t.get("name")) for t in types}

    async def issue_type_names(self, project_key: str) -> set[str]:
        """The names of the issue types *project_key* offers."""
        resp = await self._request("GET", f"/project/{project_key}")
        types = resp.json().get("issueTypes") or []
        return {str(t.get("name")) for t in types}

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

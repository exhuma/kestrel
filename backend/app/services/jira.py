"""Async Jira REST client + ``TaskSource`` adapter (feature 003).

Jira is a *task source* whose code lives in a separate repository. This client
reuses ``httpx`` (no new dependency) and targets REST v3 with ADF documents
for Cloud or v2 plain-text bodies for self-hosted Jira Server/DC. Auth is
configurable:
``basic`` (Cloud — email + API token) or ``bearer`` (Server/DC — PAT). The
token is a secret and is never logged.
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx

from app.config_models import TaskSourceConfig
from app.documents import (
    Document,
    as_document,
    render_adf,
    render_markdown,
)
from app.ports import Feedback, LifecycleEvent, SubtaskContextError, Task
from app.services.exceptions import GitError
from app.services.feedback.marker import append_comment_sentinel
from app.services.feedback.timeparse import parse_iso
from app.services.jira_document import to_text

_log = logging.getLogger("kestrel.jira")

#: Which TaskSourceConfig field names an event kind's transition id.
_TRANSITION_FIELD = {
    "start": "transition_start",
    "done": "transition_done",
    "failed": "transition_failed",
    "escalated": "transition_escalated",
    "rejected": "transition_rejected",
}


class JiraError(GitError):
    """A Jira REST call failed."""


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
        if resp.status_code >= 300:
            # Redact: neither the token nor Basic credentials are echoed.
            raise JiraError(
                f"{method} {path} -> {resp.status_code}: {resp.text}"
            )
        return resp

    async def check_health(self) -> bool:
        """Best-effort reachability + auth probe (feature 014).

        A single cheap, issue-independent, authenticated call. Never
        raises: any failure (network, auth, timeout, malformed response)
        is caught and reported as ``False``.
        """
        try:
            await self._request("GET", "/myself")
        except Exception:  # noqa: BLE001 — health checks never raise
            return False
        return True

    @staticmethod
    def _to_task(issue: dict) -> Task:
        fields = issue.get("fields") or {}
        return Task(
            ref=issue["key"],
            title=fields.get("summary") or "",
            body=to_text(fields.get("description")),
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

    async def add_comment(self, key: str, body: Document | str) -> str:
        """Post a comment; return its API URL."""
        resp = await self._request(
            "POST",
            f"/issue/{key}/comment",
            json={
                "body": render_adf(as_document(body))
                if self._cloud
                else render_markdown(as_document(body)),
            },
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
        body: str,
        extra_fields: dict[str, object] | None = None,
    ) -> str:
        """Create a native Sub-task issue linked to ``parent_key``.

        Jira's own subdivision primitive (distinct from a plain linked
        issue) — feature 012's follow-up tasks use it so the parent/child
        relationship is native, not just a body reference.
        """
        fields = {
            "project": {"key": project_key},
            "summary": summary,
            "description": self._description_body(body),
            "issuetype": {"name": "Sub-task"},
            "parent": {"key": parent_key},
        }
        if extra_fields:
            fields.update(extra_fields)
        resp = await self._request(
            "POST",
            "/issue",
            json={"fields": fields},
        )
        return resp.json()["key"]

    def _description_body(self, body: str) -> object:
        """Render a child description only when Cloud requires ADF."""
        return render_adf(as_document(body)) if self._cloud else body

    async def add_remote_link(self, key: str, url: str, title: str) -> None:
        """Add a titled web link to an issue for repository resolution."""
        await self._request(
            "POST",
            f"/issue/{key}/remotelink",
            json={"object": {"url": url, "title": title}},
        )

    async def transition_issue(self, key: str, transition_id: str) -> None:
        """Apply a configured workflow transition (feature 006)."""
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
        """Fetch every comment on an issue, oldest first (feature 013).

        Paginates via ``startAt``/``total`` (the v2 comment endpoint's own
        scheme) until every page has been read; typical RFC comment
        volume is small enough that this is always one or two calls.
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


class JiraTaskSource:
    """``TaskSource`` adapter over :class:`JiraClient` (RFC tickets)."""

    def __init__(
        self,
        client: JiraClient,
        public_base_url: str = "",
        config: "TaskSourceConfig | None" = None,
        comment_sentinel_enabled: bool = True,
        comment_sentinel: str = "[kestrel:posted]",
    ) -> None:
        """
        :param config: This source's config, carrying its lifecycle
            transition ids and time-tracking field (feature 006). ``None``
            means no native lifecycle handling is configured — every
            event falls back to the comment footer.
        """
        self._client = client
        self._base = client._base
        self._config = config
        self._comment_sentinel_enabled = comment_sentinel_enabled
        self._comment_sentinel = comment_sentinel

    async def get_task(self, ref: str) -> Task:
        return await self._client.get_issue(ref)

    async def check_health(self) -> bool:
        return await self._client.check_health()

    async def post_comment(self, ref: str, body: Document | str) -> str:
        """Post a marked Kestrel comment on ``ref``."""
        return await self._client.add_comment(
            ref,
            append_comment_sentinel(
                render_markdown(as_document(body)),
                self._comment_sentinel_enabled,
                self._comment_sentinel,
            ),
        )

    async def cleanup_artifact(self, kind: str, external_id: str) -> str:
        """Delete a recorded Jira resource when its deployment permits it."""
        if kind == "source_body":
            return "cleaned"
        if kind == "comment" and external_id:
            await self._client.delete_resource(external_id)
            return "cleaned"
        if kind == "subtask":
            await self._client.delete_issue(external_id)
            return "cleaned"
        raise ValueError(f"unsupported Jira cleanup artifact: {kind}")

    async def attach(
        self, ref: str, name: str, data: bytes, mimetype: str
    ) -> None:
        await self._client.add_attachment(ref, name, data, mimetype)

    async def publish_refined(
        self, ref: str, content: "Document | str"
    ) -> None:
        """Deliver the approved PRD as an attachment on the RFC (FR-011)."""
        text = (
            render_markdown(content)
            if isinstance(content, Document)
            else content
        )
        await self._client.add_attachment(
            ref, "PRD.md", text.encode("utf-8"), "text/markdown"
        )

    async def create_subtask(
        self, parent_ref: str, title: str, body: str
    ) -> str:
        """Create a child that inherits its parent's repository binding."""
        project_key = parent_ref.split("-", 1)[0]
        repo_field = self._config.repo_field if self._config else ""
        extra_fields = await self._repository_fields(parent_ref, repo_field)
        child_ref = await self._client.create_subtask(
            parent_ref, project_key, title, body, extra_fields
        )
        await self.complete_subtask(parent_ref, child_ref)
        return child_ref

    async def complete_subtask(self, parent_ref: str, task_ref: str) -> None:
        """Repair an existing child's repository binding when it uses links."""
        if not self._config or self._config.repo_field:
            return
        try:
            await self._copy_repository_link(parent_ref, task_ref)
        except Exception as exc:
            raise SubtaskContextError(task_ref) from exc

    async def _repository_fields(
        self, parent_ref: str, repo_field: str
    ) -> dict[str, object] | None:
        """Return the parent field binding when configured and populated."""
        if not repo_field:
            return None
        value = await self._client.get_field(parent_ref, repo_field)
        return {repo_field: value} if value and value.strip() else None

    async def _copy_repository_link(
        self, parent_ref: str, child_ref: str
    ) -> None:
        """Copy the configured repository link when no field binding exists."""
        wanted = (
            self._config.repo_link_text if self._config else "Repository"
        ).casefold()
        for link in await self._client.get_remote_links(parent_ref):
            obj = link.get("object") or {}
            if (obj.get("title") or "").casefold() != wanted:
                continue
            url = obj.get("url") or ""
            if url:
                await self._client.add_remote_link(child_ref, url, obj["title"])
            return

    def display_label(self, ref: str) -> str:
        """The ref itself: already the issue key, e.g. "RFC-123"."""
        return ref

    def deep_link_ref(self, ref: str) -> str:
        return f"{self._base}/browse/{ref}"

    async def transition(self, ref: str, event: LifecycleEvent) -> bool:
        """Apply the configured workflow transition and time field.

        Per-instance workflows are unpredictable (feature 006's whole
        motivation), so both are optional and no-op when unconfigured —
        an unset transition id is not an error, it just means this
        instance's admin hasn't enabled a distinct transition for that
        lifecycle point.
        """
        status_ok = await self._apply_transition(ref, event)
        await self._apply_time(ref, event)
        return status_ok

    async def _apply_transition(self, ref: str, event: LifecycleEvent) -> bool:
        field = _TRANSITION_FIELD[event.kind]
        transition_id = getattr(self._config, field, "") if self._config else ""
        if not transition_id:
            return False
        try:
            await self._client.transition_issue(ref, transition_id)
            return True
        except Exception:  # noqa: BLE001 — best-effort; footer is the fallback
            return False

    async def _apply_time(self, ref: str, event: LifecycleEvent) -> None:
        if not self._config or not self._config.time_spent_field:
            return
        if event.active_seconds is None:
            return
        try:
            await self._client.set_field(
                ref, self._config.time_spent_field, round(event.active_seconds)
            )
        except Exception:  # noqa: BLE001 — best-effort; footer is the fallback
            _log.exception("failed to write time_spent_field for %s", ref)

    def supports_time_spent(self) -> bool:
        return bool(self._config and self._config.time_spent_field)

    def visibility(self) -> Literal["public", "private"]:
        """Jira RFCs are externally visible (feature 008)."""
        return "public"

    async def list_comments(
        self, ref: str, since: str | None = None
    ) -> list[Feedback]:
        """List an RFC's comments as ``Feedback`` (feature 013).

        ``since`` is an ISO-8601 cutoff, filtered client-side after
        fetching every comment (Jira REST v2 has no server-side time
        filter on this endpoint).
        """
        raw = await self._client.list_comments(ref)
        cutoff = parse_iso(since) if since else None
        items = [self._to_feedback(ref, c) for c in raw]
        return [f for f in items if cutoff is None or f.created_at >= cutoff]

    @staticmethod
    def _to_feedback(ref: str, comment: dict) -> Feedback:
        author = (comment.get("author") or {}).get("displayName", "")
        return Feedback(
            external_id=f"jira-comment:{ref}:{comment['id']}",
            origin="ticket",
            author=author,
            body=to_text(comment.get("body")),
            created_at=parse_iso(comment["created"]),
        )

    async def acknowledge(
        self, _feedback: Feedback, _token: str = "eyes"
    ) -> bool:
        """Jira REST v2 has no reaction endpoint (feature 013)."""
        return False

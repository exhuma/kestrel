"""Async Jira REST client + ``TaskSource`` adapter (feature 003).

Jira is a *task source* whose code lives in a separate repository. This client
reuses ``httpx`` (no new dependency) and targets the REST **v2** API, whose
plain-text comment/description bodies keep the integration simple and work on
self-hosted Jira Server/DC — the sovereignty target. Auth is configurable:
``basic`` (Cloud — email + API token) or ``bearer`` (Server/DC — PAT). The
token is a secret and is never logged.
"""
from __future__ import annotations

import logging
from typing import Literal

import httpx

from app.config_models import TaskSourceConfig
from app.ports import Feedback, LifecycleEvent, Task
from app.services.exceptions import GitError
from app.services.feedback.timeparse import parse_iso

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
    """Thin async wrapper over the Jira REST v2 API."""

    def __init__(
        self,
        base_url: str,
        *,
        auth: str = "basic",
        email: str = "",
        token: str = "",
        verify: bool = True,
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
            base_url=f"{self._base}/rest/api/2", auth=http_auth, verify=verify
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
        self, parent_key: str, project_key: str, summary: str, body: str
    ) -> str:
        """Create a native Sub-task issue linked to ``parent_key``.

        Jira's own subdivision primitive (distinct from a plain linked
        issue) — feature 012's follow-up tasks use it so the parent/child
        relationship is native, not just a body reference.
        """
        resp = await self._request(
            "POST",
            "/issue",
            json={
                "fields": {
                    "project": {"key": project_key},
                    "summary": summary,
                    "description": body,
                    "issuetype": {"name": "Sub-task"},
                    "parent": {"key": parent_key},
                }
            },
        )
        return resp.json()["key"]

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
                "GET", f"/issue/{key}/comment",
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

    async def get_task(self, ref: str) -> Task:
        return await self._client.get_issue(ref)

    async def check_health(self) -> bool:
        return await self._client.check_health()

    async def post_comment(self, ref: str, body: str) -> str:
        return await self._client.add_comment(ref, body)

    async def attach(
        self, ref: str, name: str, data: bytes, mimetype: str
    ) -> None:
        await self._client.add_attachment(ref, name, data, mimetype)

    async def publish_refined(self, ref: str, content: str) -> None:
        """Deliver the approved PRD as an attachment on the RFC (FR-011)."""
        await self._client.add_attachment(
            ref, "PRD.md", content.encode("utf-8"), "text/markdown"
        )

    async def create_subtask(
        self, parent_ref: str, title: str, body: str
    ) -> str:
        """Create a native Sub-task issue in the parent's project."""
        project_key = parent_ref.split("-", 1)[0]
        return await self._client.create_subtask(
            parent_ref, project_key, title, body
        )

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
        return [f for f in items if cutoff is None or f.created_at > cutoff]

    @staticmethod
    def _to_feedback(ref: str, comment: dict) -> Feedback:
        author = (comment.get("author") or {}).get("displayName", "")
        return Feedback(
            external_id=f"jira-comment:{ref}:{comment['id']}",
            origin="ticket",
            author=author,
            body=comment.get("body") or "",
            created_at=parse_iso(comment["created"]),
        )

    async def acknowledge(
        self, _feedback: Feedback, _token: str = "eyes"
    ) -> bool:
        """Jira REST v2 has no reaction endpoint (feature 013)."""
        return False

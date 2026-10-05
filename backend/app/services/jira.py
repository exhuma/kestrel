"""Jira ``TaskSource`` adapter (feature 003).

Jira is a *task source* whose code lives in a separate repository. The REST
client is :mod:`app.services.jira_client`; this adapter maps the port onto
it. Comments are Documents carrying kestrel's ownership marker, rendered
once by the client (ADF on Cloud); comments read back are Documents with
their authors' accounts (feature 046).
"""

from __future__ import annotations

import logging
from typing import Literal

from app.config_models import TaskSourceConfig
from app.document_formats.adf import parse_adf
from app.document_formats.markdown import render_markdown
from app.documents import Document
from app.ports import (
    CommentPage,
    Feedback,
    LifecycleEvent,
    Person,
    SubtaskContextError,
    Task,
)
from app.services.jira_client import JiraClient, JiraError, person
from app.services.task_source_utils import (
    REFINED,
    as_posted,
    parse_iso,
    with_marker,
)

__all__ = ["JiraClient", "JiraError", "JiraTaskSource"]

_log = logging.getLogger("kestrel.jira")

#: Which TaskSourceConfig field names an event kind's transition id.
_TRANSITION_FIELD = {
    "start": "transition_start",
    "done": "transition_done",
    "failed": "transition_failed",
    "escalated": "transition_escalated",
    "rejected": "transition_rejected",
}


class JiraTaskSource:
    """``TaskSource`` adapter over :class:`JiraClient` (RFC tickets)."""

    def __init__(
        self,
        client: JiraClient,
        public_base_url: str = "",
        config: "TaskSourceConfig | None" = None,
        comment_sentinel_enabled: bool = True,
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

    async def get_task(self, ref: str) -> Task:
        """The issue, with its reporter and configured change owner."""
        field = self._config.change_owner_field if self._config else ""
        return await self._client.get_issue(ref, field)

    async def check_health(self) -> bool:
        return await self._client.check_health()

    async def post_comment(self, ref: str, body: Document) -> str:
        """Post a comment carrying kestrel's ownership marker."""
        return await self._client.add_comment(
            ref, as_posted(body, self._comment_sentinel_enabled)
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
    async def publish_refined(self, ref: str, content: Document) -> None:
        """Deliver the approved PRD as a Markdown attachment (FR-011)."""
        text = render_markdown(with_marker(content, REFINED))
        await self._client.add_attachment(
            ref, "PRD.md", text.encode("utf-8"), "text/markdown"
        )

    async def create_subtask(
        self,
        parent_ref: str,
        title: str,
        body: Document,
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
    ) -> CommentPage:
        """An RFC's comments from cursor ``since``, oldest first.

        The cursor is the last comment's ``created`` timestamp, filtered
        client-side (the endpoint has no time filter). The boundary
        comment is read again; callers deduplicate by external id.
        """
        raw = await self._client.list_comments(ref)
        cutoff = parse_iso(since) if since else None
        items = [self._to_feedback(ref, c) for c in raw]
        comments = [
            f for f in items if cutoff is None or f.created_at >= cutoff
        ]
        cursor = raw[-1]["created"] if raw else since
        return CommentPage(comments, cursor)

    @staticmethod
    def _to_feedback(ref: str, comment: dict) -> Feedback:
        return Feedback(
            external_id=f"jira-comment:{ref}:{comment['id']}",
            origin="ticket",
            author=_author(comment.get("author")),
            body=parse_adf(comment.get("body")),
            created_at=parse_iso(comment["created"]),
        )

    async def acknowledge(
        self, _feedback: Feedback, _token: str = "eyes"
    ) -> bool:
        """Jira REST v2 has no reaction endpoint (feature 013)."""
        return False


def _author(raw: object) -> Person:
    """A comment's author; without an account, only their name is known
    (an empty ``account_id`` never matches anyone)."""
    found = person(raw)
    if found is not None:
        return found
    name = raw.get("displayName") if isinstance(raw, dict) else ""
    return Person("", str(name or ""))

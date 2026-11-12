"""Jira ``TaskSource`` adapter (feature 003).

Jira is a *task source* whose code lives in a separate repository. The REST
client is :mod:`app.services.jira_client`; this adapter maps the port onto
it. Comments are Documents carrying kestrel's ownership marker, rendered
once by the client (ADF on Cloud); comments read back are Documents with
their authors' accounts (feature 046).
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from app.config_models import TaskSourceConfig
from app.document_formats.adf import parse_adf
from app.documents import Document
from app.ports import (
    CommentPage,
    Feedback,
    LifecycleEvent,
    Person,
    SubtaskContextError,
    Task,
    WorkItemState,
)
from app.services.jira_client import JiraClient, JiraError, person
from app.services.task_source_utils import as_posted, parse_iso

__all__ = ["JiraClient", "JiraError", "JiraTaskSource"]

_log = logging.getLogger("kestrel.jira")

#: Which TaskSourceConfig field names an event kind's transition id.
_TRANSITION_FIELD = {
    "start": "transition_start",
    "done": "transition_done",
}
#: What a Jira issue key looks like; only such refs go into a query.
_ISSUE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-\d+$")
#: The status category key Jira gives every finished status.
_DONE_CATEGORY = "done"
#: How many work items one search page reads.
_BATCH = 100


class JiraTaskSource:
    """``TaskSource`` adapter over :class:`JiraClient` (RFC tickets)."""

    def __init__(
        self,
        client: JiraClient,
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
        self._config = config
        self._comment_sentinel_enabled = comment_sentinel_enabled

    async def get_task(self, ref: str) -> Task:
        """The issue, with its reporter and configured change owner."""
        field = self._config.change_owner_field if self._config else ""
        return await self._client.get_issue(ref, field)

    async def check_health(self) -> bool:
        """Reachable and signed in, and the work-item settings name types
        that exist, so a typo shows on the status icon, not on CAB-2.

        :raises JiraError: Naming each setting Jira does not know.
        """
        await self._client.check_health()
        if self._config is not None:
            problems = await self._work_item_problems(self._config)
            if problems:
                raise JiraError("; ".join(problems))
        return True

    async def _work_item_problems(self, config: TaskSourceConfig) -> list[str]:
        links = await self._client.link_type_names()
        wanted = [config.work_items_blocks_link_type]
        if config.work_items_project:
            wanted.append(config.work_items_link_type)
        problems = [
            f"no issue link type named {name!r}"
            for name in wanted if name not in links
        ]
        project = config.work_items_project
        if project:
            types = await self._client.issue_type_names(project)
            if config.work_item_type() not in types:
                problems.append(
                    f"project {project} has no issue type named "
                    f"{config.work_item_type()!r}"
                )
        return problems

    async def post_comment(self, ref: str, body: Document) -> str:
        """Post a comment carrying kestrel's ownership marker."""
        return await self._client.add_comment(
            ref, as_posted(body, self._comment_sentinel_enabled)
        )

    async def create_subtask(
        self,
        parent_ref: str,
        title: str,
        body: Document,
        key: str = "",
    ) -> str:
        """Create one approved task's work item: a sub-task of the request
        that inherits its repository binding, or an issue in
        ``work_items_project`` linked to the request."""
        if key:
            found = await self._client.find_by_label(key)
            if found:
                _log.info("work item %s already exists as %s", key, found)
                return found
        config = self._settings()
        project = config.work_items_project
        fields: dict[str, object] = {
            "project": {"key": project or parent_ref.split("-", 1)[0]},
            "summary": title,
            "issuetype": {"name": config.work_item_type()},
        }
        if key:
            fields["labels"] = [key]
        if not project:
            fields["parent"] = {"key": parent_ref}
            fields |= await self._repository_fields(
                parent_ref, config.repo_field
            ) or {}
        child_ref = await self._client.create_issue(fields, body)
        if project:
            await self._client.link_issues(
                config.work_items_link_type, child_ref, parent_ref
            )
            await self._copy_repository_link(parent_ref, child_ref)
        else:
            await self.complete_subtask(parent_ref, child_ref)
        return child_ref

    def _settings(self) -> TaskSourceConfig:
        """This source's config, or the defaults when it has none."""
        return self._config or TaskSourceConfig.model_construct(type="jira")

    async def link_subtasks(self, blocking_ref: str, blocked_ref: str) -> None:
        """Link two work items with the configured "blocks" link type."""
        config = self._settings()
        await self._client.link_issues(
            config.work_items_blocks_link_type, blocking_ref, blocked_ref
        )

    async def attach_document(
        self, ref: str, name: str, document: Document
    ) -> str:
        """Attach *document* to the issue as a Markdown file."""
        return await self._client.attach_markdown(ref, name, document)

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
        field = _TRANSITION_FIELD.get(event.kind)
        if not field or not self._config:
            return False
        transition_id = getattr(self._config, field, "")
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

    def supports_handover(self) -> bool:
        """Jira says who has a work item: its assignee (#99)."""
        return True

    async def work_item_states(
        self, refs: list[str]
    ) -> dict[str, WorkItemState]:
        """Who has each work item, and whether it is done, in one search
        (two with ``work_items_jql``). An item is kestrel's when it is
        assigned to the account behind the token, or matches the query.
        """
        keys = ", ".join(f'"{ref}"' for ref in refs if _ISSUE_KEY.match(ref))
        if not keys:
            return {}
        me = await self._client.myself()
        issues = await self._client.search_issues(
            f"key in ({keys})", fields=["assignee", "status"],
            max_results=_BATCH,
        )
        matched = await self._handover_matches(keys)
        return {
            str(issue["key"]): _item_state(issue, me, matched)
            for issue in issues
        }

    async def _handover_matches(self, keys: str) -> set[str]:
        """The keys among *keys* that match ``work_items_jql``."""
        jql = self._settings().work_items_jql.strip()
        if not jql:
            return set()
        issues = await self._client.search_issues(
            f"key in ({keys}) AND ({jql})", fields=["summary"],
            max_results=_BATCH,
        )
        return {str(issue["key"]) for issue in issues}

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


def _item_state(
    issue: dict, me: Person | None, matched: set[str]
) -> WorkItemState:
    """One searched issue's hand-over and done state."""
    fields = issue.get("fields") or {}
    assignee = person(fields.get("assignee"))
    mine = (
        me is not None and assignee is not None
        and assignee.account_id == me.account_id
    )
    category = (fields.get("status") or {}).get("statusCategory") or {}
    return WorkItemState(
        handed_to_kestrel=mine or str(issue.get("key")) in matched,
        done=category.get("key") == _DONE_CATEGORY,
    )


def _author(raw: object) -> Person:
    """A comment's author; without an account, only their name is known
    (an empty ``account_id`` never matches anyone)."""
    found = person(raw)
    if found is not None:
        return found
    name = raw.get("displayName") if isinstance(raw, dict) else ""
    return Person("", str(name or ""))

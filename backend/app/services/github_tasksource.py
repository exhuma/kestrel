"""``GitHubTaskSource`` — the ``TaskSource`` adapter over :class:`GitHubClient`.

Split out of ``services/github.py`` (feature 013, US3) to keep that module
under the repo's 500-line ceiling once ``GitHubCodeHost``'s PR-review
read/acknowledge capability joined the existing pull-request-open path —
mirrors ``ports.py``'s own ``TaskSource``/``CodeHost`` role split.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Callable, Literal

from app.config_models import TaskSourceConfig
from app.documents import Document, as_document, render_markdown
from app.markers import Marker, apply_markers
from app.ports import Feedback, LifecycleEvent, Task
from app.services.feedback.marker import append_comment_sentinel
from app.services.feedback.timeparse import parse_iso
from app.services.github import GitHubClient, parse_github_ref
from app.services.github_cleanup import close_issue, delete_issue_comment
from app.services.workflow_text import append_sentinel

#: Prefix minted onto every issue-comment ``Feedback.external_id`` (feature
#: 013) — carries the repo so ``acknowledge`` can reconstruct the reaction
#: endpoint from just the ``Feedback`` object.
_COMMENT_ID_PREFIX = "gh-issue-comment:"

#: Which TaskSourceConfig field names a failure-terminal event's label.
_TERMINAL_LABEL_FIELD = {
    "failed": "failed_label",
    "escalated": "escalated_label",
    "rejected": "rejected_label",
}


class GitHubTaskSource:
    """``TaskSource`` adapter over :class:`GitHubClient` (issues)."""

    def __init__(
        self,
        client: GitHubClient,
        public_base_url: str = "",
        config_for: "Callable[[str], TaskSourceConfig | None] | None" = None,
        comment_sentinel_enabled: bool = True,
        comment_sentinel: str = "[kestrel:posted]",
    ) -> None:
        """
        :param config_for: Resolves a repo (``owner/name``) to the
            :class:`TaskSourceConfig` carrying its lifecycle labels
            (feature 006). ``None`` (or no match) falls back to the
            model's own defaults.
        """
        self._client = client
        self._public_base_url = public_base_url.rstrip("/")
        self._config_for = config_for
        self._comment_sentinel_enabled = comment_sentinel_enabled
        self._comment_sentinel = comment_sentinel

    async def get_task(self, ref: str) -> Task:
        repo, number = parse_github_ref(ref)
        issue = await self._client.get_issue(repo, number)
        return Task(ref=ref, title=issue.title, body=issue.body)

    async def check_health(self) -> bool:
        """Delegates to the shared client — same connection/credential
        as this profile's code host, when GitHub plays both roles."""
        return await self._client.check_health()

    async def post_comment(self, ref: str, body: Document | str) -> str:
        repo, number = parse_github_ref(ref)
        return await self._client.create_issue_comment(
            repo,
            number,
            append_comment_sentinel(
                render_markdown(as_document(body)),
                self._comment_sentinel_enabled,
                self._comment_sentinel,
            ),
        )

    async def attach(
        self, _ref: str, _name: str, _data: bytes, _mimetype: str
    ) -> None:
        """No-op: GitHub issues have no attachment API. The PRD goes in the
        issue body; screenshots ride along committed in the PR's ``.kestrel``
        folder."""

    async def publish_refined(
        self, ref: str, content: "Document | str"
    ) -> None:
        """Write the approved PRD back to the issue body with the sentinel."""
        repo, number = parse_github_ref(ref)
        text = (
            render_markdown(content)
            if isinstance(content, Document)
            else content
        )
        await self._client.update_issue(repo, number, append_sentinel(text))

    async def create_subtask(
        self,
        parent_ref: str,
        title: str,
        body: str,
        markers: Sequence[Marker] = (),
    ) -> str:
        """Create a follow-up issue in the same repo (feature 012).

        Linked to its parent via a reference line in the body (GitHub
        issues have no native sub-issue type at this API layer); created
        with no labels at all, so it can never carry the trigger label.
        """
        body = apply_markers(body, markers)
        repo, parent_number = parse_github_ref(parent_ref)
        full_body = f"Sub-task of #{parent_number}\n\n{body}"
        number = await self._client.create_issue(repo, title, full_body)
        return f"{repo}#{number}"

    async def complete_subtask(self, _parent_ref: str, _task_ref: str) -> None:
        """No-op because GitHub child creation includes all required context."""

    def display_label(self, ref: str) -> str:
        """The ref itself: already "owner/name#123"."""
        return ref

    def deep_link_ref(self, ref: str) -> str:
        repo, number = parse_github_ref(ref)
        return f"https://github.com/{repo}/issues/{number}"

    def _config(self, repo: str) -> TaskSourceConfig:
        found = self._config_for(repo) if self._config_for else None
        return found or TaskSourceConfig(type="github", watched_repos=[repo])

    async def transition(self, ref: str, event: LifecycleEvent) -> bool:
        """Add/remove issue labels for ``event.kind`` (feature 006).

        GitHub issues have no native "in progress"/"done" state — labels
        are the closest native primitive. ``done`` only removes the
        in-progress label (never force-closes the issue: the existing
        ``Closes #n`` PR body already closes it on merge, and closing it
        earlier would misrepresent an unmerged PR as resolved).
        """
        repo, number = parse_github_ref(ref)
        cfg = self._config(repo)
        try:
            if event.kind == "start":
                await self._client.add_label(
                    repo, number, cfg.in_progress_label
                )
            elif event.kind == "done":
                await self._client.remove_label(
                    repo, number, cfg.in_progress_label
                )
            else:
                terminal_label = getattr(cfg, _TERMINAL_LABEL_FIELD[event.kind])
                await self._client.remove_label(
                    repo, number, cfg.in_progress_label
                )
                await self._client.add_label(repo, number, terminal_label)
            return True
        except Exception:  # noqa: BLE001 — best-effort; footer is the fallback
            return False

    def supports_time_spent(self) -> bool:
        """GitHub issues have no native time-tracking field."""
        return False

    def visibility(self) -> Literal["public", "private"]:
        """GitHub issues are externally visible (feature 008)."""
        return "public"

    async def list_comments(
        self, ref: str, since: str | None = None
    ) -> list[Feedback]:
        """List an issue's comments as ``Feedback`` (feature 013).

        Bot-authored comments (``user.type == "Bot"``) are excluded here,
        at the source, rather than downstream in the intake pipeline —
        this is the one adapter with the metadata to tell (research.md
        R6). ``since`` is round-tripped as GitHub's own ISO-8601 filter,
        with an extra client-side inclusive check. Re-reading the boundary
        preserves comments created at the same timestamp; durable external-ID
        deduplication drops the already-processed comment.
        """
        repo, number = parse_github_ref(ref)
        raw = await self._client.list_issue_comments(repo, number, since=since)
        cutoff = parse_iso(since) if since else None
        return [
            item
            for item in (self._to_feedback(repo, c) for c in raw)
            if item is not None
            and (cutoff is None or item.created_at >= cutoff)
        ]

    def _to_feedback(self, repo: str, comment: dict) -> Feedback | None:
        user = comment.get("user") or {}
        if user.get("type") == "Bot":
            return None
        return Feedback(
            external_id=f"{_COMMENT_ID_PREFIX}{repo}#{comment['id']}",
            origin="ticket",
            author=user.get("login", ""),
            body=comment.get("body") or "",
            created_at=parse_iso(comment["created_at"]),
        )

    async def acknowledge(
        self, feedback: Feedback, token: str = "eyes"
    ) -> bool:
        """React to the triggering comment (feature 013, R8)."""
        parsed = _parse_comment_external_id(feedback.external_id)
        if parsed is None:
            return False
        repo, comment_id = parsed
        try:
            await self._client.add_issue_comment_reaction(
                repo, comment_id, token
            )
            return True
        except Exception:  # noqa: BLE001 — best-effort acknowledgment
            return False

    async def cleanup_artifact(self, kind: str, external_id: str) -> str:
        """Reverse a recorded GitHub-owned resource without broad discovery."""
        if kind == "source_body":
            repo, number = parse_github_ref(external_id.partition("\0")[0])
            await self._client.update_issue(
                repo, number, external_id.partition("\0")[2]
            )
            return "cleaned"
        if kind == "subtask":
            repo, number = parse_github_ref(external_id)
            await close_issue(self._client, repo, number)
            return "closed"
        if kind == "comment":
            parsed = _parse_comment_url(external_id)
            if parsed is None:
                return "absent"
            repo, comment_id = parsed
            await delete_issue_comment(self._client, repo, comment_id)
            return "cleaned"
        raise ValueError(f"unsupported GitHub cleanup artifact: {kind}")


def _parse_comment_external_id(external_id: str) -> tuple[str, int] | None:
    """Recover ``(repo, comment_id)`` from a minted issue-comment id."""
    if not external_id.startswith(_COMMENT_ID_PREFIX):
        return None
    repo, _, comment_id = external_id[len(_COMMENT_ID_PREFIX) :].rpartition("#")
    if not repo or not comment_id.isdigit():
        return None
    return repo, int(comment_id)


def _parse_comment_url(url: str) -> tuple[str, int] | None:
    """Extract a repository and comment id from GitHub's returned URL."""
    marker = "/issues/"
    if marker not in url or "#issuecomment-" not in url:
        return None
    repo = url.split(marker, 1)[0].removeprefix("https://github.com/")
    comment_id = url.rsplit("#issuecomment-", 1)[1]
    return (repo, int(comment_id)) if repo and comment_id.isdigit() else None

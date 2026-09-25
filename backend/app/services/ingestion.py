"""Shared ingestion path: decide whether an issue should start a run.

Called by both the webhook handler and the reconciliation loop so the
one-run-per-issue and dismissal rules live in exactly one place (feature
002, FR-007/FR-008/FR-008a/FR-013a).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from app.models_board import Workflow
from app.models_board_records import AcceptedTaskIntake
from app.persistence.board_store import WorkflowAlreadyExistsError
from app.persistence.child_task_store import (
    ChildTaskLinks,
    get_child_task_store,
)
from app.persistence.dismissal_store import DismissalStore, get_dismissal_store
from app.services.board.bootstrap import (
    get_board_service,
    get_quarantine_service,
)
from app.services.board.quarantine import NewTaskIntake, QuarantineService
from app.services.board.service import BoardService
from app.services.task_scheduler import ScheduledTask, integration_branch
from app.services.task_source_utils import has_subtask_sentinel
from app.services.task_sources import (
    TaskSourceRegistry,
    get_task_source_registry,
)

_log = logging.getLogger("kestrel.ingestion")


@dataclass(frozen=True)
class BoardIntake:
    """The board-domain collaborators ``maybe_start_run`` routes through.

    Bundled into one object to keep :class:`IngestionService`'s
    constructor within the repo's argument-count limit.

    :param quarantine: The fail-closed untrusted-input boundary.
    :param board: Creates the accepted-task workflow once content clears
        quarantine.
    """

    quarantine: QuarantineService
    board: BoardService


class IngestionService:
    """Starts a board workflow for a qualifying issue, idempotently."""

    def __init__(
        self,
        settings: Settings,
        task_sources: TaskSourceRegistry,
        dismissals: DismissalStore,
        board_intake: BoardIntake,
        child_tasks: ChildTaskLinks | None = None,
    ) -> None:
        self.settings = settings
        self.task_sources = task_sources
        self.dismissals = dismissals
        self.board_intake = board_intake
        self.child_tasks = child_tasks

    def is_watched(self, repo: str) -> bool:
        """Return whether ``repo`` is in a github source's allow-list."""
        return self.settings.github_source_for(repo) is not None

    def has_run(self, task_ref: str) -> bool:
        """Return whether a board workflow already exists for ``task_ref``."""
        return any(
            w.task_ref == task_ref
            for w in self.board_intake.board.list_workflows()
        )

    async def maybe_start_run(
        self,
        *,
        source: str,
        task_ref: str,
        code_repo: str,
        issue_number: int | None = None,
        base_branch: str | None = None,
    ) -> str | None:
        """
        Start a board workflow for a ticket unless it is filtered out.

        The single source-neutral entry point every trigger calls (GitHub
        webhook, GitHub reconcile, Jira poll) so one-run-per-ticket, dismissal,
        and (GitHub) watched-repo rules live in one place (FR-031/FR-033/
        FR-034). A future Jira webhook is one more caller of this method.

        Filters, in order: (GitHub) unwatched repo, dismissed ticket, an
        existing board workflow for the ``task_ref``. Otherwise the ticket's
        canonical body is fetched — never the webhook payload's own body —
        and screened through the untrusted-input boundary (FR-018) before
        any board workflow is created (feature 026). A failure to create
        raises before any row persists, leaving nothing for reconciliation
        to trip over (FR-013a).

        :param source: Run origin (``github-issue`` | ``jira-issue``).
        :param task_ref: Source-native ticket id (dedup/dismissal key).
        :param code_repo: The target code repository (``owner/name``).
        :param issue_number: GitHub issue number; unused (board workflows
            are keyed by ``task_ref``, not a numeric issue id).
        :param base_branch: Resolved base branch, when already known
            (Jira); ``None`` lets the board default to ``"main"``.
        :returns: The new board workflow id, the quarantine-hosting
            workflow id, or ``None`` if filtered out or already started.
        """
        del issue_number  # kept for caller-signature compatibility
        if source == "github-issue" and not self.is_watched(code_repo):
            _log.info("ingest outcome=skipped-filtered %s", task_ref)
            return None
        if self.dismissals.is_dismissed(task_ref):
            _log.info("ingest outcome=dismissed %s", task_ref)
            return None
        if self.has_run(task_ref):
            _log.info("ingest outcome=skipped-duplicate %s", task_ref)
            return None
        scheduled = self._scheduled_child(task_ref, code_repo)
        if scheduled is not None:
            base_branch = integration_branch(scheduled)
        return await self._start_via_board(
            source=source,
            task_ref=task_ref,
            code_repo=code_repo,
            base_branch=base_branch,
        )

    async def _start_via_board(
        self,
        *,
        source: str,
        task_ref: str,
        code_repo: str,
        base_branch: str | None,
    ) -> str | None:
        """Canonically fetch, screen, and (if safe) create a board workflow.

        The task source is re-fetched here rather than trusting any
        webhook-carried body (Edge Cases: content may change between
        delivery and use), and every body is screened before it can create
        board state (FR-018/FR-019).
        """
        task_source = self.task_sources.sources.get(source)
        if task_source is None:
            _log.warning("ingest outcome=no-task-source %s", task_ref)
            return None
        task = await task_source.get_task(task_ref)
        outcome = await self.board_intake.quarantine.intake_for_new_task(
            NewTaskIntake(source=source, task_ref=task_ref, body=task.body)
        )
        if not outcome.released:
            _log.info("ingest outcome=quarantined %s", task_ref)
            return outcome.workflow_id
        try:
            workflow = self.board_intake.board.create_workflow_from_intake(
                AcceptedTaskIntake(
                    source=source,
                    task_ref=task_ref,
                    repo=code_repo,
                    base_branch=base_branch or "main",
                    source_visibility=task_source.visibility(),
                    title=task.title,
                    skip_decomposition=has_subtask_sentinel(task.body),
                )
            )
        except WorkflowAlreadyExistsError:
            _log.info("ingest outcome=skipped-duplicate-board %s", task_ref)
            return None
        if self.child_tasks is not None:
            self.child_tasks.record_run(task_ref, workflow.id)
        _log.info("ingest outcome=started %s -> %s", task_ref, workflow.id)
        return workflow.id

    def _scheduled_child(
        self, task_ref: str, repo: str
    ) -> ScheduledTask | None:
        """Build scheduler input only for a linked child with DAG metadata.

        Prerequisite/repo-modification gating (the old driver's
        ``_is_startable``) is not carried over: it read the old fixed-step
        run list for readiness/status signals that have no board
        equivalent, and the property it protected — at most one writer
        per repository — is already enforced at claim time by the board's
        own workspace lease (one active write lease per repo). A linked
        child now starts as soon as its task source makes it visible; only
        its ``integration_branch`` metadata is still consulted.
        """
        if self.child_tasks is None:
            return None
        details = self.child_tasks.scheduling_details(task_ref)
        if details is None:
            return None
        return ScheduledTask(task_ref, repo, details.integration_branch)

    async def observe_child_source_state(
        self, task_ref: str, state: str
    ) -> None:
        """Observe a linked child's source lifecycle state and re-adopt reopen.

        An open observation attempts a successor before recording open, so only
        a durable prior closed observation can satisfy the store's claim.
        Unknown tasks are harmless because every store operation is conditional
        on an existing child link.
        """
        if self.child_tasks is None:
            return
        if state == "closed":
            self.child_tasks.observe_source_state(task_ref, state)
            return
        for workflow in reversed(self.board_intake.board.list_workflows()):
            if workflow.task_ref != task_ref:
                continue
            if await self.maybe_start_reopened_successor(parent=workflow):
                return
        self.child_tasks.observe_source_state(task_ref, state)

    async def observe_missing_child_source_tasks(
        self, prefix: str, qualifying: set[str]
    ) -> None:
        """Close linked children that left a poll source's qualifying set."""
        if self.child_tasks is None:
            return
        for task_ref in self.child_tasks.linked_refs(prefix) - qualifying:
            await self.observe_child_source_state(task_ref, "closed")

    async def observe_child_retrigger(
        self, task_ref: str, generation: str | None
    ) -> None:
        """Re-adopt a linked local child after a generation change."""
        if generation is None or self.child_tasks is None:
            return
        if self.child_tasks.observe_generation(task_ref, generation):
            await self.observe_child_source_state(task_ref, "open")

    async def maybe_start_reopened_successor(
        self, *, parent: Workflow
    ) -> str | None:
        """Start one linked successor after a claimed child reopen.

        This intentionally does not call :meth:`has_run`: the parent itself
        proves a workflow exists, while the child-store claim limits a
        validated closed-to-open transition to exactly one successor.
        Ordinary ingestion retains its existing duplicate filter.
        """
        if self.child_tasks is None:
            return None
        if self.dismissals.is_dismissed(parent.task_ref):
            _log.info("re-adoption outcome=dismissed %s", parent.task_ref)
            return None
        if not self.child_tasks.claim_reopen(parent.task_ref, parent.id):
            _log.info("re-adoption outcome=skipped %s", parent.task_ref)
            return None
        try:
            workflow_id = await self.start_successor_run(parent=parent)
        except Exception:
            self.child_tasks.release_reopen(parent.task_ref)
            raise
        if workflow_id is None:
            self.child_tasks.release_reopen(parent.task_ref)
            return None
        self.child_tasks.complete_reopen(parent.task_ref, workflow_id)
        return workflow_id

    async def start_successor_run(self, *, parent: Workflow) -> str | None:
        """
        Start a board workflow continuing ``parent`` after its own path is
        exhausted.

        Reachable only via :meth:`maybe_start_reopened_successor`, itself
        only reached from :meth:`observe_child_source_state` — never from
        ordinary ingestion. Deliberately bypasses :meth:`maybe_start_run`'s
        watched/dismissed/``has_run`` filters the same way that method
        does: this ticket already proved watched and not dismissed when
        ``parent`` itself started, and ``has_run`` exists to stop
        *unrelated* re-ingestion of an already-labelled ticket, not to
        block an intentional, explicitly linked continuation of a
        workflow that already exists. Still funnels through
        :meth:`_start_via_board` (the same convergence point
        :meth:`maybe_start_run` uses), so quarantine screening and
        board-workflow creation stay defined in exactly one place.

        :param parent: The finished workflow this successor continues
            from — its ``repo``/``task_ref``/``source``/``base_branch``
            carry over unchanged (same ticket, same target repo).
        :returns: The new workflow's id, or ``None`` if it could not be
            started (no task source, or it quarantined without a board
            workflow yet — the same outcomes :meth:`maybe_start_run` can
            return).
        """
        workflow_id = await self._start_via_board(
            source=parent.source,
            task_ref=parent.task_ref,
            code_repo=parent.repo,
            base_branch=parent.base_branch,
        )
        _log.info(
            "ingest outcome=successor parent=%s -> %s", parent.id, workflow_id
        )
        return workflow_id


@lru_cache
def get_ingestion_service() -> IngestionService:
    """Return the process-wide IngestionService singleton."""
    return IngestionService(
        get_settings(),
        get_task_source_registry(),
        get_dismissal_store(),
        BoardIntake(get_quarantine_service(), get_board_service()),
        get_child_task_store(),
    )

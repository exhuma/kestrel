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
from app.models_board import CardKind
from app.models_board_records import AcceptedTaskIntake
from app.persistence.board_store import WorkflowAlreadyExistsError
from app.persistence.dismissal_store import DismissalStore, get_dismissal_store
from app.services.board.bootstrap import (
    get_board_service,
    get_gates_service,
    get_quarantine_service,
)
from app.services.board.gates import GatesService
from app.services.board.quarantine import NewTaskIntake, QuarantineService
from app.services.board.service import BoardService
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
    :param gates: Creates the initial understanding-gate card (with its
        ``HumanGateRecord``) once ``board`` has a workflow to hang it
        off — ``BoardService`` cannot create it directly without
        importing ``GatesService`` back, which would cycle.
    """

    quarantine: QuarantineService
    board: BoardService
    gates: GatesService


class IngestionService:
    """Starts a board workflow for a qualifying issue, idempotently."""

    def __init__(
        self,
        settings: Settings,
        task_sources: TaskSourceRegistry,
        dismissals: DismissalStore,
        board_intake: BoardIntake,
    ) -> None:
        self.settings = settings
        self.task_sources = task_sources
        self.dismissals = dismissals
        self.board_intake = board_intake

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
            if outcome.workflow_id is not None:
                self.board_intake.board.announce(outcome.workflow_id)
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
                    body=outcome.safe_content or "",
                )
            )
        except WorkflowAlreadyExistsError:
            _log.info("ingest outcome=skipped-duplicate-board %s", task_ref)
            return None
        self.board_intake.gates.create_gate(
            workflow.id,
            kind=CardKind.UNDERSTANDING_GATE.value,
            title="Confirm understanding",
            requested_decision="confirm_understanding",
        )
        _log.info("ingest outcome=started %s -> %s", task_ref, workflow.id)
        return workflow.id


@lru_cache
def get_ingestion_service() -> IngestionService:
    """Return the process-wide IngestionService singleton."""
    return IngestionService(
        get_settings(),
        get_task_source_registry(),
        get_dismissal_store(),
        BoardIntake(
            get_quarantine_service(), get_board_service(), get_gates_service()
        ),
    )

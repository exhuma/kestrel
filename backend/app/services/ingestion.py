"""Shared ingestion path: decide whether an issue should start a run.

Called by both the webhook handler and the reconciliation loop so the
one-run-per-issue and dismissal rules live in exactly one place (feature
002, FR-007/FR-008/FR-008a/FR-013a).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from app.models_board import CardState, Workflow
from app.models_board_records import AcceptedTaskIntake
from app.persistence.board_store import WorkflowAlreadyExistsError
from app.persistence.dismissal_store import DismissalStore, get_dismissal_store
from app.ports import Task
from app.services.board.bootstrap import (
    get_board_service,
    get_quarantine_service,
)
from app.services.board.intake import awaits_release, open_screening_card
from app.services.board.live_activity import (
    LiveActivity,
    get_live_activity,
    tracking,
)
from app.services.board.quarantine import (
    ExistingWorkflowIntake,
    QuarantineService,
)
from app.services.board.service import BoardService
from app.services.task_sources import (
    TaskSourceRegistry,
    get_task_source_registry,
)

_log = logging.getLogger("kestrel.ingestion")

#: Strong references to in-flight released-intake continuations.
_TASKS: set[asyncio.Task[None]] = set()


@dataclass(frozen=True)
class BoardIntake:
    """The board-domain collaborators ``maybe_start_run`` routes through.

    Bundled into one object to keep :class:`IngestionService`'s
    constructor within the repo's argument-count limit.

    :param quarantine: The fail-closed untrusted-input boundary.
    :param board: Creates the request, and runs its screening lifecycle
        (feature 032).
    :param live: Shows screening as live work (feature 033).
    """

    quarantine: QuarantineService
    board: BoardService
    live: LiveActivity | None = None


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
        #: Requests this process is screening right now — never screened
        #: twice at once, and what tells a live screening from one a
        #: restart interrupted (FR-006).
        self._screening: set[str] = set()

    def is_watched(self, repo: str) -> bool:
        """Return whether ``repo`` is in a github source's allow-list."""
        return self.settings.github_source_for(repo) is not None

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
        existing board workflow for the ``task_ref`` (whose interrupted
        screening, if any, is resumed). Otherwise the request is created
        at once, showing "Screening input", and the ticket's canonical
        body — never the webhook payload's own — is screened through the
        untrusted-input boundary (FR-018) before it reaches the request
        (feature 032).

        :param source: Run origin (``github-issue`` | ``jira-issue``).
        :param task_ref: Source-native ticket id (dedup/dismissal key).
        :param code_repo: The target code repository (``owner/name``).
        :param issue_number: GitHub issue number; unused (board workflows
            are keyed by ``task_ref``, not a numeric issue id).
        :param base_branch: Resolved base branch, when already known
            (Jira); ``None`` lets the board default to ``"main"``.
        :returns: The new request's workflow id (whether it passed
            screening or was quarantined in place), or ``None`` if
            filtered out or already started.
        """
        del issue_number  # kept for caller-signature compatibility
        if source == "github-issue" and not self.is_watched(code_repo):
            _log.info("ingest outcome=skipped-filtered %s", task_ref)
            return None
        if self.dismissals.is_dismissed(task_ref):
            _log.info("ingest outcome=dismissed %s", task_ref)
            return None
        existing = self._workflow_for(task_ref)
        if existing is not None:
            await self._resume_screening(existing)
            return None
        return await self._start_via_board(
            source=source,
            task_ref=task_ref,
            code_repo=code_repo,
            base_branch=base_branch,
        )

    @property
    def _quarantine(self) -> QuarantineService:
        return self.board_intake.quarantine

    def _workflow_for(self, task_ref: str) -> Workflow | None:
        return next(
            (
                w for w in self.board_intake.board.list_workflows()
                if w.task_ref == task_ref
            ),
            None,
        )

    async def _start_via_board(
        self,
        *,
        source: str,
        task_ref: str,
        code_repo: str,
        base_branch: str | None,
    ) -> str | None:
        """Show the request, then screen its canonically fetched body.

        The request exists on the board before screening starts — its
        title only the ticket ref, holding no unscreened content — so a
        slow classification is visible rather than silent (feature 032,
        #68). The task source is re-fetched here rather than trusting
        any webhook-carried body (content may change between delivery
        and use), and the body is screened before it reaches the
        request (FR-018/FR-019).
        """
        task_source = self.task_sources.sources.get(source)
        if task_source is None:
            _log.warning("ingest outcome=no-task-source %s", task_ref)
            return None
        task = await task_source.get_task(task_ref)
        try:
            workflow, card = self.board_intake.board.open_screening(
                AcceptedTaskIntake(
                    source=source,
                    task_ref=task_ref,
                    repo=code_repo,
                    base_branch=base_branch or "main",
                    source_visibility=task_source.visibility(),
                    title=task_ref,
                )
            )
        except WorkflowAlreadyExistsError:
            _log.info("ingest outcome=skipped-duplicate-board %s", task_ref)
            return None
        await self._screen(workflow, card.id, task)
        return workflow.id

    async def _screen(
        self, workflow: Workflow, card_id: str | None, task: Task
    ) -> None:
        """Screen *task*'s body for *workflow*: pass it on, or quarantine
        it in place (FR-003/FR-004). *card_id* is the screening card to
        settle — ``None`` when continuing after a release."""
        self._screening.add(workflow.id)
        try:
            with tracking(self.board_intake.live, workflow.id, "screening"):
                outcome = await self._quarantine.intake_for_existing_workflow(
                    ExistingWorkflowIntake(
                        identity_ref=workflow.task_ref, category="intake",
                        content=task.body, workflow=workflow,
                    )
                )
        finally:
            self._screening.discard(workflow.id)
        board = self.board_intake.board
        if outcome.released:
            board.pass_screening(
                workflow.id, title=task.title,
                body=outcome.safe_content or task.body, card_id=card_id,
            )
            _log.info("ingest outcome=started %s", workflow.task_ref)
            return
        if card_id is not None:
            board.settle_screening(
                card_id, CardState.CANCELLED.value,
                event_type="screening.quarantined", wake=False,
            )
        _log.info("ingest outcome=quarantined %s", workflow.task_ref)

    async def _resume_screening(self, workflow: Workflow) -> None:
        """Screen again a request whose screening was interrupted — e.g.
        by a restart (FR-006). Otherwise the ticket already has its
        request and nothing more happens."""
        card = open_screening_card(
            self.board_intake.board.list_cards(workflow.id)
        )
        if card is None or workflow.id in self._screening:
            _log.info("ingest outcome=skipped-duplicate %s", workflow.task_ref)
            return
        task = await self._fetch(workflow)
        if task is not None:
            await self._screen(workflow, card.id, task)

    async def continue_intake(self, workflow_id: str) -> None:
        """Continue a request whose intake quarantine was released
        (FR-005): screened again against the canonical ticket, which
        passes at once when its content is what was released, and is
        classified afresh when it has changed since."""
        board = self.board_intake.board
        workflow = board.get_workflow(workflow_id)
        if workflow is None or not awaits_release(
            workflow, board.list_cards(workflow_id)
        ):
            return
        task = await self._fetch(workflow)
        if task is not None:
            await self._screen(workflow, None, task)

    async def _fetch(self, workflow: Workflow) -> Task | None:
        source = self.task_sources.sources.get(workflow.source)
        if source is None:
            _log.warning(
                "ingest outcome=no-task-source %s", workflow.task_ref
            )
            return None
        return await source.get_task(workflow.task_ref)


def schedule_intake_continuation(workflow_id: str) -> None:
    """Continue a released intake in the background (FR-005) — the
    caller (the release route) must not wait on a task-source fetch and
    a classification."""
    task = asyncio.create_task(
        get_ingestion_service().continue_intake(workflow_id)
    )
    _TASKS.add(task)
    task.add_done_callback(_after_continuation)


def _after_continuation(task: asyncio.Task[None]) -> None:
    _TASKS.discard(task)
    if not task.cancelled() and task.exception() is not None:
        _log.error(
            "continuing a released intake failed", exc_info=task.exception()
        )


@lru_cache
def get_ingestion_service() -> IngestionService:
    """Return the process-wide IngestionService singleton."""
    return IngestionService(
        get_settings(),
        get_task_source_registry(),
        get_dismissal_store(),
        BoardIntake(
            get_quarantine_service(), get_board_service(),
            get_live_activity(),
        ),
    )

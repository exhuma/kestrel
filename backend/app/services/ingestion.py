"""Shared ingestion path: decide whether an issue should start a run.

Called by both the webhook handler and the reconciliation loop so the
one-run-per-issue and dismissal rules live in exactly one place (feature
002, FR-007/FR-008/FR-008a/FR-013a).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.models_workflow import WorkflowRun
from app.persistence.child_task_store import (
    ChildTaskLinks,
    get_child_task_store,
)
from app.persistence.dismissal_store import DismissalStore, get_dismissal_store
from app.services.task_scheduler import (
    ScheduledTask,
    integration_branch,
    is_startable,
    modifying_repositories,
)
from app.services.workflows import WorkflowService, get_workflow_service

_log = logging.getLogger("kestrel.ingestion")


class IngestionService:
    """Starts a run for a qualifying issue, idempotently."""

    def __init__(
        self,
        settings: Settings,
        workflows: WorkflowService,
        dismissals: DismissalStore,
        child_tasks: ChildTaskLinks | None = None,
    ) -> None:
        self.settings = settings
        self.workflows = workflows
        self.dismissals = dismissals
        self.child_tasks = child_tasks

    def is_watched(self, repo: str) -> bool:
        """Return whether ``repo`` is in a github source's allow-list."""
        return self.settings.github_source_for(repo) is not None

    def has_run(self, task_ref: str) -> bool:
        """Return whether a run already exists for ``task_ref``."""
        return any(r.task_ref == task_ref for r in self.workflows.list())

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
        Start a run for a ticket unless it is filtered out.

        The single source-neutral entry point every trigger calls (GitHub
        webhook, GitHub reconcile, Jira poll) so one-run-per-ticket, dismissal,
        and (GitHub) watched-repo rules live in one place (FR-031/FR-033/
        FR-034). A future Jira webhook is one more caller of this method.

        Filters, in order: (GitHub) unwatched repo, dismissed ticket, an
        existing run for the ``task_ref``. Otherwise creates a run and returns
        its id. A failure to create raises before any run row persists, leaving
        nothing for reconciliation to trip over (FR-013a).

        :param source: Run origin (``github-issue`` | ``jira-issue``).
        :param task_ref: Source-native ticket id (dedup/dismissal key).
        :param code_repo: The target code repository (``owner/name``).
        :param issue_number: GitHub issue number; ``None`` for Jira.
        :param base_branch: Resolved base branch (Jira); ``None`` ⇒ resolved by
            the driver.
        :returns: The new run id, or ``None`` if filtered out.
        """
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
        if scheduled is not None and not self._is_startable(scheduled):
            _log.info("ingest outcome=skipped-blocked %s", task_ref)
            return None
        if scheduled is not None:
            base_branch = integration_branch(scheduled)
        run_id = await self.workflows.create(
            code_repo,
            issue_number,
            source=source,
            task_ref=task_ref,
            base_branch=base_branch,
        )
        if self.child_tasks is not None:
            self.child_tasks.record_run(task_ref, run_id)
        _log.info("ingest outcome=started %s -> %s", task_ref, run_id)
        return run_id

    def _scheduled_child(
        self, task_ref: str, repo: str
    ) -> ScheduledTask | None:
        """Build scheduler input only for a linked child with DAG metadata."""
        if self.child_tasks is None:
            return None
        details = self.child_tasks.scheduling_details(task_ref)
        if details is None:
            return None
        return ScheduledTask(
            task_ref, repo, details.prerequisites, details.integration_branch
        )

    def _is_startable(self, task: ScheduledTask) -> bool:
        """Check prerequisites and repository modification exclusion."""
        assert self.child_tasks is not None
        runs = self.workflows.list()
        ready_ids = {
            run.id for run in runs if run.status == "technically_ready"
        }
        ready_nodes = self.child_tasks.ready_task_node_ids(ready_ids)
        return is_startable(task, ready_nodes, modifying_repositories(runs))

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
        for run in reversed(self.workflows.list()):
            if run.task_ref != task_ref:
                continue
            if await self.maybe_start_reopened_successor(parent=run):
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
        self, *, parent: WorkflowRun
    ) -> str | None:
        """Start one linked successor after a claimed child reopen.

        This intentionally does not call :meth:`has_run`: the parent itself
        proves a run exists, while the child-store claim limits a validated
        closed-to-open transition to exactly one successor. Ordinary ingestion
        retains its existing duplicate filter.
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
            run_id = await self.start_successor_run(parent=parent)
        except Exception:
            self.child_tasks.release_reopen(parent.task_ref)
            raise
        self.child_tasks.complete_reopen(parent.task_ref, run_id)
        return run_id

    async def start_successor_run(self, *, parent: WorkflowRun) -> str:
        """
        Start a run continuing ``parent`` after its own path is exhausted.

        Called only by ``FeedbackDispatcher``'s terminal-run branch
        (feature 013, US4) when marked feedback arrives for a `done` run
        whose change request has since merged/closed (or never existed)
        — never by ingestion/reconcile. Deliberately bypasses
        :meth:`maybe_start_run`'s watched/dismissed/``has_run`` filters:
        this ticket already proved watched and not dismissed when
        ``parent`` itself started, and the ``has_run`` dedup rule exists
        to stop *unrelated* re-ingestion of a ticket whose GitHub trigger
        label a `done` transition deliberately never removes (so
        reconcile would otherwise keep finding it labelled) — it is not
        meant to block an intentional, explicitly linked continuation of
        a run that already exists. Still funnels through
        ``WorkflowService.create`` (the same sole convergence point
        :meth:`maybe_start_run`/``reset.rerun`` already use), so branch-
        naming/workspace-provisioning stays defined in exactly one place.

        :param parent: The finished run this successor continues from —
            its ``repo``/``task_ref``/``source``/``base_branch`` carry
            over unchanged (same ticket, same target repo).
        :returns: The new run's id.
        """
        run_id = await self.workflows.create(
            parent.repo,
            parent.issue_number,
            source=parent.source,
            task_ref=parent.task_ref,
            base_branch=parent.base_branch or None,
            parent_run_id=parent.id,
        )
        _log.info("ingest outcome=successor parent=%s -> %s", parent.id, run_id)
        return run_id


@lru_cache
def get_ingestion_service() -> IngestionService:
    """Return the process-wide IngestionService singleton."""
    return IngestionService(
        get_settings(),
        get_workflow_service(),
        get_dismissal_store(),
        get_child_task_store(),
    )

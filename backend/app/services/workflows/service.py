"""WorkflowService: lifecycle/CRUD and gate-decision handling."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import uuid
from typing import Callable

from app.backends.base import Backend, TurnRequest, TurnResult
from app.config import Settings
from app.models_workflow import Step, StepSession, WorkflowRun, WorkflowStep
from app.notifications import Notifier
from app.persistence.dismissal_store import DismissalStore
from app.policy import BackendPolicy
from app.questionnaire import InterviewEnvelope
from app.services.exceptions import WorkflowNotFoundError
from app.services.git import GitService
from app.services.github import GitHubClient, GitHubCodeHost, GitHubTaskSource
from app.services.time_tracking import set_clock
from app.services.workflows import artifacts, driver, gate, screenshots
from app.services.workflows import sessions as sessions_mod
from app.services.workflows.gate import _Control, _Decision
from app.services.workflows.shared import (
    _TERMINAL_STATUSES,
    _log_driver_exception,
    _now_utc,
    _slug_ref,
)
from app.storage.registry import SessionRegistry
from app.storage.workflow_bus import WorkflowBus
from app.storage.workflow_registry import WorkflowRegistry

_WF_TASKS: set[asyncio.Task] = set()
_logger = logging.getLogger(__name__)


class WorkflowService:
    """Drives workflow runs through refine -> plan -> implement -> PR."""

    def __init__(
        self,
        settings: Settings,
        sessions: SessionRegistry,
        workflows: WorkflowRegistry,
        backends: BackendPolicy,
        git: GitService,
        github: GitHubClient,
        notifier: Notifier,
        bus: WorkflowBus | None = None,
        dismissals: DismissalStore | None = None,
        sources: dict[str, object] | None = None,
        code_hosts: dict[str, object] | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.workflows = workflows
        self.backends = backends
        self.git = git
        self.github = github
        self.notifier = notifier
        self.bus = bus
        #: Task Source / Code Host per ``run.source`` (feature 003). GitHub and
        #: manual runs collapse onto the GitHub adapters over ``github``; the
        #: factory registers the Jira source and a self-hosted code host. Built
        #: from ``github`` by default so existing callers need no change.
        _gh_source = GitHubTaskSource(github, settings.public_base_url)
        _gh_host = GitHubCodeHost(github, settings.git_base)
        self.sources = sources or {
            "manual": _gh_source, "github-issue": _gh_source,
        }
        self.code_hosts = code_hosts or {
            "manual": _gh_host, "github-issue": _gh_host,
        }
        self._fallback_source = _gh_source
        self._fallback_host = _gh_host
        #: Records a dismissal on abandon so a still-labelled ingested issue
        #: is not re-ingested (feature 002, FR-008a). Optional so unit tests
        #: that don't exercise ingestion need not provide one.
        self.dismissals = dismissals
        self._control: dict[str, _Control] = {}
        #: Driver task per run, so an abandon can cancel the in-flight
        #: orchestration for exactly that run.
        self._tasks: dict[str, asyncio.Task] = {}

    def _spawn_driver(self, workflow_id: str, coro) -> None:
        """Launch a run's driver task and track it by id for abandon."""
        task = asyncio.create_task(coro)
        self._tasks[workflow_id] = task
        _WF_TASKS.add(task)
        task.add_done_callback(_WF_TASKS.discard)
        task.add_done_callback(
            lambda t, wid=workflow_id: self._tasks.pop(wid, None)
        )
        task.add_done_callback(
            lambda t, wid=workflow_id: _log_driver_exception(t, wid)
        )

    def _new_control(self) -> _Control:
        return gate.new_control()

    def _task_source(self, run: WorkflowRun):
        """The bound TaskSource for a run's origin (feature 003)."""
        return self.sources.get(run.source, self._fallback_source)

    def _code_host(self, run: WorkflowRun):
        """The bound CodeHost for a run's target repository (feature 003)."""
        return self.code_hosts.get(run.source, self._fallback_host)

    def _save(self, run: WorkflowRun) -> None:
        """
        Persist the run and notify if its new status needs
        attention.

        The single choke point for every state-transition
        checkpoint in this service — every internal call site
        uses ``self._save(run)`` instead of calling
        ``self.workflows.save(run)`` directly, so no call site
        can forget to notify, and no call site needs to judge for
        itself whether its status is notification-worthy (the
        notifier does that filtering once, centrally).

        :param run: The run to checkpoint.
        """
        if run.status in _TERMINAL_STATUSES and run.clock_state is not None:
            set_clock(run, None, _now_utc())
        self.workflows.save(run)
        self.notifier.notify(run)
        if self.bus is not None:
            # Tick every SSE subscriber so the UI re-reads this run
            # (state, chips, deliverable) instead of polling.
            self.bus.publish(run.id)

    def _safe_save(self, run: WorkflowRun) -> None:
        """Persist a run, tolerating a secondary failure while already
        handling one.

        Used inside exception/cleanup handlers so a failing DB write here
        doesn't also kill the driver task with an unretrieved exception —
        the caller has already mutated ``run.status`` on the in-memory
        object the registry holds, so that much survives even if this
        persist doesn't; the failure itself is still logged loudly rather
        than silently swallowed.
        """
        try:
            self._save(run)
        except Exception:
            _logger.exception(
                "workflow %s: failed to persist status %r",
                run.id, run.status,
            )

    # ---- queries -------------------------------------------------------
    def get(self, workflow_id: str) -> WorkflowRun:
        run = self.workflows.get(workflow_id)
        if run is None:
            raise WorkflowNotFoundError(workflow_id)
        return run

    def list(self) -> list[WorkflowRun]:
        return self.workflows.list()

    def current_session_id(self, run: WorkflowRun) -> str | None:
        for step in run.steps:
            if step.status in (
                "running",
                "awaiting_input",
                "awaiting_approval",
            ):
                return step.session_id
        return None

    # ---- workspace provisioning (per-run worktree, US3) ----------------
    def _mirror_dir(self, repo: str) -> str:
        """Path of the per-repo shared bare mirror."""
        return artifacts.mirror_dir(self.settings.workspace_root, repo)

    # ---- step-handover artifacts (.kestrel/) ---------------------------
    def _ensure_artifact_dir(self, run: WorkflowRun) -> None:
        """Pick (once) this run's ``.kestrel/<date>-<serial>/`` folder."""
        artifacts.ensure_artifact_dir(run, self._save)

    def _write_artifact(
        self, run: WorkflowRun, filename: str, content: str
    ) -> None:
        """Write a handover artifact into this run's artifact folder."""
        artifacts.write_artifact(run, filename, content, self._save)

    def _artifact_slot(
        self, step: str, run: WorkflowRun, filename: str, content: str
    ) -> str:
        """Value to interpolate for a prior artifact in a step's prompt."""
        return artifacts.artifact_slot(
            step, run, filename, content, self.backends.backend_for
        )

    def _debug_log(
        self, run: WorkflowRun, heading: str, content: str
    ) -> None:
        """Append one entry to the run's coder<->verifier dialogue log."""
        artifacts.debug_log(
            run, heading, content, enabled=self.settings.workflow_debug
        )

    async def _teardown_workspace(
        self, run: WorkflowRun, *, force: bool = False
    ) -> None:
        """Remove a run's worktree and directory; best-effort, isolated.

        Closes the workspace leak (only abandon cleaned up before) so a
        finished/failed run does not linger. Never disturbs another run's
        worktree (feature 002, FR-017). Skipped when ``workflow_debug`` is on
        — the worktree and its dialogue transcript (see ``_debug_log``) stay
        inspectable — unless ``force``, which an explicit abandon still uses
        to actually drop the workspace on request.
        """
        if not run.workspace:
            return
        if self.settings.workflow_debug and not force:
            _logger.info(
                "workflow_debug: keeping workspace for run %s (%s)",
                run.id, run.workspace,
            )
            return
        # Preserve this run's screenshots to the durable dir before the
        # worktree they live in is removed, so the gallery keeps working
        # once the run is done/failed. Best-effort, never blocks teardown.
        with contextlib.suppress(Exception):
            screenshots.persist_screenshots(
                run, self.settings.screenshots_root
            )
        with contextlib.suppress(Exception):
            await self.git.remove_worktree(
                self._mirror_dir(run.repo), run.workspace
            )
        shutil.rmtree(run.workspace, ignore_errors=True)

    # ---- commands ------------------------------------------------------
    async def create(
        self,
        repo: str,
        issue_number: int | None = None,
        *,
        source: str = "manual",
        task_ref: str | None = None,
        base_branch: str | None = None,
    ) -> str:
        """Create and drive a run for a ticket.

        Source-neutral (feature 003): ``repo`` is the *code repository*;
        ``task_ref`` is the source-native ticket id (defaults to
        ``owner/name#n`` for GitHub/manual). A Jira run passes ``task_ref`` (the
        RFC key), ``issue_number=None``, and a resolved ``base_branch``.
        """
        tref = task_ref or f"{repo}#{issue_number}"
        if issue_number is not None:
            branch = f"kestrel/issue-{issue_number}"
        else:
            branch = f"kestrel/{_slug_ref(tref)}"
        run = WorkflowRun(
            id="wf-" + uuid.uuid4().hex[:8],
            repo=repo,
            issue_number=issue_number,
            task_ref=tref,
            base_branch=base_branch or "",
            branch=branch,
            workspace=os.path.join(
                self.settings.workspace_root,
                f"wf-{uuid.uuid4().hex[:8]}",
            ),
            steps=[WorkflowStep(name=step) for step in Step.sequence()],
            source=source,
        )
        self.workflows.create(run)
        self._control[run.id] = self._new_control()
        self._spawn_driver(run.id, driver.drive(self, run.id))
        return run.id

    def _awaiting_input_step(self, run: WorkflowRun) -> WorkflowStep:
        """Return whichever step is currently awaiting a reply."""
        return gate.awaiting_input_step(run)

    def reply(self, workflow_id: str, text: str) -> None:
        run = self.get(workflow_id)
        gate.reply(run, self._control[workflow_id], text)

    def _interview_state(
        self, workflow_id: str
    ) -> tuple[WorkflowRun, WorkflowStep, InterviewEnvelope]:
        """Return the run/step/envelope for a pending refine interview."""
        return gate.interview_state(self.get(workflow_id))

    def save_draft(
        self, workflow_id: str, answers: dict[str, object]
    ) -> None:
        """Persist a partial answer set without finalizing the interview."""
        run, step, envelope = self._interview_state(workflow_id)
        gate.save_draft(run, step, envelope, answers, self.workflows.save)

    def submit_answers(
        self, workflow_id: str, answers: dict[str, object]
    ) -> None:
        """Answer whichever step's pending structured questionnaire."""
        run = self.get(workflow_id)
        step = self._awaiting_input_step(run)
        # Safety net: with the flag on, tolerate missing required answers
        # (they go through blank) while still rejecting malformed ones.
        gate.submit_answers(
            self._control[workflow_id], step, answers,
            partial=self.settings.allow_incomplete_answers,
        )

    def approve(self, workflow_id: str, deliverable: str | None = None) -> None:
        self._resolve(workflow_id, _Decision(True, deliverable))

    def reject(
        self,
        workflow_id: str,
        refinement_prompt: str | None = None,
    ) -> None:
        """
        Reject the current gate.

        With a refinement prompt the phase regenerates its
        deliverable from the same session; without one the run
        ends as rejected.

        :param workflow_id: Id of the run whose gate to reject.
        :param refinement_prompt: Feedback to regenerate with,
            or None to end the run.
        """
        self._resolve(
            workflow_id,
            _Decision(False, refinement=refinement_prompt),
        )

    def _resolve(self, workflow_id: str, decision: _Decision) -> None:
        run = self.get(workflow_id)
        gate.resolve(run, self._control[workflow_id], decision)

    async def _abandon_common(self, workflow_id: str) -> WorkflowRun:
        """Cancel a run and drop every trace of its local work.

        Shared by :meth:`delete` and :meth:`cleanup`: cancels the driver
        task, then terminates and deletes every session that ran in the
        run's workspace (the coordinator, each specialist, plan,
        implement) — killing any in-flight subprocess and dropping the
        session's records, not just the latest one a step still points at.
        Forgets the control state, removes the registry record and its
        persisted rows, and deletes the cloned workspace. Deliberately
        never touches GitHub itself — callers decide separately whether to
        reach the remote (e.g. branch deletion).

        :param workflow_id: Id of the run to abandon.
        :raises WorkflowNotFoundError: If the run is unknown.
        """
        run = self.get(workflow_id)
        task = self._tasks.pop(workflow_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except BaseException:  # cancellation or a late step error
                pass
        # Every session a run spawned records cwd == run.workspace (the same
        # attribution SessionService.list_summaries uses), so match on that
        # to catch them all — not just the latest id each step points at.
        # Union in the step pointers defensively.
        session_ids = {
            record.session_id
            for record in self.sessions.list()
            if run.workspace and record.cwd == run.workspace
        }
        session_ids.update(
            step.session_id for step in run.steps if step.session_id
        )
        for session_id in session_ids:
            # A session may have run on any backend; each ignores ids it
            # doesn't own, so ask them all to stop it.
            for backend in self.backends.backends():
                backend.terminate(session_id)
            if self.sessions.get(session_id) is not None:
                self.sessions.remove(session_id)
        self._control.pop(workflow_id, None)
        self.workflows.remove(workflow_id)
        # Explicit user action: drop the workspace even in workflow_debug.
        await self._teardown_workspace(run, force=True)
        return run

    async def delete(self, workflow_id: str) -> None:
        """
        Abandon a run: cancel it and drop every trace of its local work.

        Deliberately never touches GitHub — abandoning drops work only, it
        does not close issues, comment, or open/close PRs, and it leaves
        the branch (local mirror and remote) exactly as it was.

        :param workflow_id: Id of the run to abandon.
        :raises WorkflowNotFoundError: If the run is unknown.
        """
        run = await self._abandon_common(workflow_id)
        # Dismiss the issue so a still-labelled ingested run is not
        # re-created by the webhook or reconciliation (feature 002,
        # FR-008a). Cleared when the trigger label is removed.
        if self.dismissals is not None:
            self.dismissals.add(
                run.task_ref or f"{run.repo}#{run.issue_number}"
            )

    async def cleanup(self, workflow_id: str) -> None:
        """
        Fully reset a run so its task is picked up as new on the next poll.

        Unlike :meth:`delete`, this reaches the remote: it also force-
        deletes the run's branch from both kestrel's local mirror and the
        actual GitHub/GitLab remote (if it was ever pushed), and clears
        any dismissal instead of adding one — so ingestion/reconciliation
        treats the underlying ticket as brand new.

        :param workflow_id: Id of the run to clean up.
        :raises WorkflowNotFoundError: If the run is unknown.
        """
        run = await self._abandon_common(workflow_id)
        mirror = self._mirror_dir(run.repo)
        await self.git.delete_local_branch(mirror, run.branch)
        await self.git.delete_remote_branch(
            mirror, run.branch, self._code_host(run).git_credential()
        )
        if self.dismissals is not None:
            self.dismissals.clear(
                run.task_ref or f"{run.repo}#{run.issue_number}"
            )

    # ---- orchestration -------------------------------------------------
    async def _await_gate(self, workflow_id: str) -> _Decision:
        return await gate.await_gate(self._control[workflow_id])

    async def recover(self) -> None:
        """Resume persisted runs after a process restart."""
        await driver.recover(self)

    def _recover_one(self, run: WorkflowRun) -> None:
        """Recover a single persisted run (see :meth:`recover`)."""
        driver.recover_one(self, run)

    async def _deliver(self, run: WorkflowRun) -> None:
        """Commit, push, open the change request, and finish the run."""
        await driver.deliver(self, run)

    def _show_sessions(
        self, run: WorkflowRun, slots: list[StepSession]
    ) -> None:
        """Publish the sessions active on the refine step right now."""
        sessions_mod.show_sessions(run, slots, self._save)

    def _watch_activity(
        self, run: WorkflowRun, session_id: str, slot: StepSession
    ) -> asyncio.Task:
        """Track a session's live activity onto its chip."""
        return sessions_mod.watch_activity(
            self.sessions, self._save, run, session_id, slot
        )

    async def _run_turn_tracked(
        self,
        run: WorkflowRun,
        backend: Backend,
        req: TurnRequest,
        slot: StepSession,
        bind: Callable[[str], None],
    ) -> TurnResult:
        """Run one turn while streaming its live activity onto the chip."""
        tracker = sessions_mod.ChipTracker(slot, bind, self._watch_activity)
        return await sessions_mod.run_turn_tracked(
            run, backend, req, tracker
        )

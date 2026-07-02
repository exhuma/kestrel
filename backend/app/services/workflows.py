"""Orchestrates the GitHub issue -> code workflow over sessions."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from app.models_workflow import WorkflowRun, WorkflowStep
from app.policy import get_policy
from app.services.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
)
from app.services.git import GitService
from app.services.github import GitHubClient
from app.services.runner import SessionRunner
from app.services.workflow_text import (
    append_sentinel,
    extract_plan,
    extract_refined_issue,
    has_sentinel,
)
from app.storage.registry import SessionRegistry, get_registry
from app.storage.workflow_registry import (
    WorkflowRegistry,
    get_workflow_registry,
)

_WF_TASKS: set[asyncio.Task] = set()
_logger = logging.getLogger(__name__)

REFINE_PROMPT = (
    "You are refining a GitHub issue before implementation. Read the issue "
    "below and the surrounding codebase. Ask clarifying, interview-style "
    "questions ONE round at a time. When you have enough detail, output the "
    "complete refined issue wrapped EXACTLY in <REFINED_ISSUE> and "
    "</REFINED_ISSUE> tags and nothing else. Do not edit any files.\n\n"
    "ISSUE:\n{issue}"
)
PLAN_PROMPT = (
    "Read this refined GitHub issue and the codebase, then produce a concise "
    "implementation plan. Do not use the ExitPlanMode tool and do not write "
    "the plan to a file — this session is headless and cannot approve a "
    "plan that way. Instead, output the complete plan directly in your "
    "final response, wrapped EXACTLY in <PLAN> and </PLAN> tags and nothing "
    "else. Do not edit any files.\n\nISSUE:\n{issue}"
)
IMPLEMENT_PROMPT = (
    "Implement the plan you just produced. Make all necessary code edits in "
    "this repository now."
)


@dataclass
class _Control:
    """Async coordination for one run (kept off the serialisable model).

    Always build via WorkflowService._new_control() so the future binds to
    the running loop — never rely on defaults here.
    """

    gate: asyncio.Future
    replies: asyncio.Queue


@dataclass
class _Decision:
    approved: bool
    deliverable: str | None = None


class WorkflowService:
    """Drives workflow runs through refine -> plan -> implement -> PR."""

    def __init__(
        self,
        settings: Settings,
        sessions: SessionRegistry,
        workflows: WorkflowRegistry,
        runner: SessionRunner,
        git: GitService,
        github: GitHubClient,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.workflows = workflows
        self.runner = runner
        self.git = git
        self.github = github
        self._control: dict[str, _Control] = {}

    def _new_control(self) -> _Control:
        loop = asyncio.get_running_loop()
        return _Control(gate=loop.create_future(), replies=asyncio.Queue())

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
            if step.status in ("running", "awaiting_input", "awaiting_approval"):
                return step.session_id
        return None

    # ---- commands ------------------------------------------------------
    async def create(self, repo: str, issue_number: int) -> str:
        run = WorkflowRun(
            id="wf-" + uuid.uuid4().hex[:8],
            repo=repo,
            issue_number=issue_number,
            branch=f"kestrel/issue-{issue_number}",
            workspace=os.path.join(
                self.settings.workspace_root,
                f"wf-{uuid.uuid4().hex[:8]}",
            ),
            steps=[
                WorkflowStep(name="refine"),
                WorkflowStep(name="plan"),
                WorkflowStep(name="implement"),
            ],
        )
        self.workflows.create(run)
        self._control[run.id] = self._new_control()
        task = asyncio.create_task(self._drive(run.id))
        _WF_TASKS.add(task)
        task.add_done_callback(_WF_TASKS.discard)
        return run.id

    def reply(self, workflow_id: str, text: str) -> None:
        run = self.get(workflow_id)
        step = run.steps[0]
        if step.name != "refine" or step.status != "awaiting_input":
            raise InvalidWorkflowStateError("not awaiting a refine reply")
        self._control[workflow_id].replies.put_nowait(text)

    def approve(self, workflow_id: str, deliverable: str | None = None) -> None:
        self._resolve(workflow_id, _Decision(True, deliverable))

    def reject(self, workflow_id: str) -> None:
        self._resolve(workflow_id, _Decision(False))

    def _resolve(self, workflow_id: str, decision: _Decision) -> None:
        run = self.get(workflow_id)
        # Only an approval gate accepts approve/reject. Guarding on the
        # run's phase (not gate.done()) closes the window between gates
        # where a fresh, not-yet-awaited future would be pre-armed.
        if not run.status.endswith("_approval"):
            raise InvalidWorkflowStateError("no gate awaiting a decision")
        self._control[workflow_id].gate.set_result(decision)

    # ---- orchestration -------------------------------------------------
    async def _await_gate(self, workflow_id: str) -> _Decision:
        control = self._control[workflow_id]
        decision = await control.gate
        control.gate = asyncio.get_running_loop().create_future()
        return decision

    def _result_text(self, session_id: str) -> str:
        rec = self.sessions.get(session_id)
        if rec is None:
            return ""
        for ev in reversed(rec.events):
            if ev.type == "result":
                value = ev.raw.get("result")
                return value if isinstance(value, str) else ""
        return ""

    async def _drive(self, workflow_id: str) -> None:
        run = self.get(workflow_id)
        try:
            run.status = "cloning"
            issue = await self.github.get_issue(run.repo, run.issue_number)
            run.issue_title = issue.title
            run.base_branch = await self.github.get_default_branch(run.repo)
            remote = f"{self.settings.git_base}/{run.repo}.git"
            await self.git.clone(remote, run.workspace)
            await self.git.checkout_branch(run.workspace, run.branch)

            if has_sentinel(issue.body):
                run.steps[0].status = "done"
                run.steps[0].deliverable = issue.body
            else:
                await self._refine(run, issue.body)

            await self._plan(run)
            await self._implement(run)

            run.status = "opening_pr"
            await self.git.commit_all(run.workspace, f"Implement #{run.issue_number}")
            await self.git.push(run.workspace, run.branch)
            run.pr_url = await self.github.create_pull_request(
                run.repo,
                head=run.branch,
                base=run.base_branch,
                title=f"{run.issue_title} (#{run.issue_number})",
                body=f"Closes #{run.issue_number}\n\nOpened by kestrel.",
            )
            run.status = "done"
        except _Rejected:
            run.status = "rejected"
        except Exception as exc:  # record, do not crash the loop
            _logger.exception(
                "workflow %s (%s#%s) failed during %s",
                workflow_id, run.repo, run.issue_number, run.status,
            )
            run.status = "failed"
            run.error = str(exc)

    async def _refine(self, run: WorkflowRun, body: str) -> None:
        step = run.steps[0]
        prompt = REFINE_PROMPT.format(issue=body)
        sid: str | None = None
        model = get_policy().model_for("refine")
        step.model = model
        while True:
            run.status = "refining"
            step.status = "running"
            sid = await self.runner.run_blocking(
                prompt, run.workspace, "plan", resume_id=sid,
                on_session_id=lambda s: setattr(step, "session_id", s),
                model=model,
            )
            text = self._result_text(sid)
            refined = extract_refined_issue(text)
            if refined is not None:
                step.deliverable = refined
                step.status = "awaiting_approval"
                run.status = "awaiting_refine_approval"
                decision = await self._await_gate(run.id)
                if not decision.approved:
                    raise _Rejected()
                final = decision.deliverable or refined
                await self.github.update_issue(
                    run.repo, run.issue_number, append_sentinel(final)
                )
                step.status = "done"
                return
            # Not yet refined: the agent is asking a clarifying question.
            # Surface it as the step's deliverable so the UI can show it
            # without switching to the raw session feed.
            step.deliverable = text
            step.status = "awaiting_input"
            run.status = "awaiting_refine_input"
            prompt = await self._control[run.id].replies.get()

    async def _plan(self, run: WorkflowRun) -> None:
        step = run.steps[1]
        run.status = "planning"
        step.status = "running"
        refined = run.steps[0].deliverable or ""
        model = get_policy().model_for("plan")
        step.model = model
        sid = await self.runner.run_blocking(
            PLAN_PROMPT.format(issue=refined), run.workspace, "plan",
            on_session_id=lambda s: setattr(step, "session_id", s),
            model=model,
        )
        text = self._result_text(sid)
        # Prefer the tagged block; fall back to the raw text so a run still
        # gets a reviewable deliverable if the model doesn't comply (e.g.
        # it falls into its native Plan Mode and tries ExitPlanMode instead).
        step.deliverable = extract_plan(text) or text
        step.status = "awaiting_approval"
        run.status = "awaiting_plan_approval"
        decision = await self._await_gate(run.id)
        if not decision.approved:
            raise _Rejected()
        step.status = "done"
        # implement resumes this plan session via run.steps[1].session_id
        # (set by the on_session_id callback above).

    async def _implement(self, run: WorkflowRun) -> None:
        step = run.steps[2]
        run.status = "implementing"
        step.status = "running"
        model = get_policy().model_for("implement")
        step.model = model
        sid = await self.runner.run_blocking(
            IMPLEMENT_PROMPT, run.workspace, "acceptEdits",
            resume_id=run.steps[1].session_id,
            on_session_id=lambda s: setattr(step, "session_id", s),
            model=model,
        )
        step.deliverable = await self.git.diff(run.workspace)
        step.status = "awaiting_approval"
        run.status = "awaiting_implement_approval"
        decision = await self._await_gate(run.id)
        if not decision.approved:
            raise _Rejected()
        step.status = "done"


class _Rejected(Exception):
    """Internal signal that a gate was rejected."""


@lru_cache
def get_workflow_service() -> WorkflowService:
    """Return the process-wide WorkflowService singleton."""
    settings = get_settings()
    registry = get_registry()
    return WorkflowService(
        settings=settings,
        sessions=registry,
        workflows=get_workflow_registry(),
        runner=SessionRunner(settings, registry),
        git=GitService(settings.github_token),
        github=GitHubClient(settings.github_api_base, settings.github_token),
    )

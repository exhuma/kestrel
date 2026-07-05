"""Orchestrates the GitHub issue -> code workflow over sessions."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from app.backends.base import Backend, TurnRequest, TurnResult
from app.config import Settings, get_settings
from app.models_workflow import StepSession, WorkflowRun, WorkflowStep
from app.notifications import InAppNotifier, Notifier
from app.persistence.notification_store import get_notification_store
from app.storage.notification_bus import get_notification_bus
from app.policy import BackendPolicy, get_backend_policy, get_policy
from app.profiles import get_profile, roster_summary
from app.questionnaire import (
    GenerationIssue,
    InterviewEnvelope,
    ProfileMeta,
    QAEntry,
    Question,
    Questionnaire,
    build_envelope,
    format_answers,
    parse_envelope,
    parse_questionnaire_json,
    render_assumptions_and_risks,
    render_qa,
    to_entries,
    validate_answers,
)
from app.services.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
)
from app.services.git import GitService
from app.services.github import GitHubClient
from app.services.workflow_text import (
    activity_for,
    append_sentinel,
    extract_coverage,
    extract_plan,
    extract_profiles,
    extract_questionnaire,
    extract_refined_issue,
    has_sentinel,
)
from app.storage.registry import SessionRegistry, get_registry
from app.storage.workflow_bus import WorkflowBus, get_workflow_bus
from app.storage.workflow_registry import (
    WorkflowRegistry,
    get_workflow_registry,
)

_WF_TASKS: set[asyncio.Task] = set()
_logger = logging.getLogger(__name__)

#: Statuses that cannot survive a restart: their claude
#: subprocess (or transient side-effect) died with the process.
_TRANSIENT = (
    "pending", "cloning", "refining",
    "planning", "implementing", "opening_pr",
)

#: Guard on the coordinator loop so a misbehaving agent can't spin
#: the interview forever.
MAX_REFINE_ROUNDS = 3

COORDINATOR_PROMPT = (
    "You are the refinement coordinator for a GitHub issue. Read the "
    "issue and the surrounding codebase, and consider the answers "
    "gathered so far. Decide which stakeholder profiles — if any — "
    "still need to be interviewed in the NEXT round.\n"
    "Prefer RESTRAINT: pick the FEWEST profiles whose perspective this "
    "issue genuinely needs. Every profile you add spends another agent "
    "session and asks the requester more questions, so never summon a "
    "specialist 'just in case'. For a small, unambiguous change it is "
    "correct to pick just requester/developer — or an empty set, if no "
    "clarification is needed at all. Summon a specialist ONLY when the "
    "issue clearly raises a decision in its domain; lean on each "
    "profile's when-to-summon signal in the roster below (for example: "
    "the architect only for larger, distributed, or structural work; "
    "the DBA only when the data model changes; infosec only for "
    "sensitive-data or auth; UX only for a user-facing surface).\n"
    "Choose from this roster (you may also name a new profile id if a "
    "needed stakeholder is genuinely missing):\n{roster}\n"
    "Return ONLY a JSON array of profile ids wrapped EXACTLY in "
    "<PROFILES> and </PROFILES> tags and nothing else, e.g. "
    '<PROFILES>["requester", "infosec"]</PROFILES>. Return an empty '
    "array <PROFILES>[]</PROFILES> once enough detail has been gathered "
    "and no further questions are needed. Do not edit any files.\n\n"
    "ISSUE:\n{issue}\n\n{answers}"
)
RECONCILE_PROMPT = (
    "Several stakeholder profiles were interviewed in PARALLEL about "
    "this GitHub issue and, unable to see each other's questions, "
    "proposed the pooled set below. Consolidate it into the FEWEST, "
    "SIMPLEST questions that still capture every decision the human "
    "must make.\n"
    "Below is the pool as JSON — each question with its \"id\", the "
    '"audience" profile that asked it, its "prompt", "why", "type", '
    '"required", "options", and "waiver_label" — followed by the '
    "roster describing each profile's remit.\n"
    "Rules:\n"
    "- FOLD every group of questions that turn on the SAME underlying "
    "fact into ONE question. Overlap counts EVEN WHEN the framings "
    "differ across domains: e.g. Product asking 'how should accounts "
    "be created?' and Eng asking 'is this open self-registration or a "
    "fixed/seeded set of users?' are the SAME decision — emit one "
    "question, not two.\n"
    "- Assign each resulting question to the SINGLE profile whose "
    "domain best owns it (set its \"audience\" to one of the input "
    "audiences), and keep only questions worth asking.\n"
    "- Phrase each question as simply as possible. Do NOT drop detail "
    "that changes the ANSWER, but drop redundant justification. Make "
    "requester/Product questions the PLAINEST and least technical of "
    "all.\n"
    "- Preserve a sensible \"type\" and, for select types, real "
    "\"options\"; carry over each kept question's waiver intent.\n"
    "- ACCOUNT FOR EVERY input question. In each consolidated "
    "question's \"folded_from\" list, put the \"id\" of every pooled "
    "question it represents — both the one you based it on and any you "
    "merged into it. Every input id MUST appear in exactly one "
    "\"folded_from\". This is how a real fold is told apart from an "
    "accidental drop; if an input's concern no longer matters, still "
    "fold its id into the closest surviving question rather than "
    "leaving it out.\n"
    "Output ONLY the consolidated questionnaire as a single JSON "
    "object wrapped EXACTLY in <QUESTIONS> and </QUESTIONS> tags and "
    "nothing else, matching this shape:\n"
    '{{"questions": [{{"id": "q1", "audience": "requester", '
    '"prompt": "...", "why": "...", "type": "single_select", '
    '"required": true, "waiver_label": "Unknown / N/A", '
    '"folded_from": ["requester:q1", "developer:q2"], '
    '"options": [{{"value": "a", "label": "Option A"}}]}}]}}\n'
    "Do not edit any files.\n\nISSUE:\n{issue}\n\n"
    "QUESTIONS:\n{questions}\n\nROSTER:\n{roster}"
)
CRITIC_PROMPT = (
    "You are a completeness critic reviewing a consolidated "
    "questionnaire for a GitHub issue. Several stakeholder profiles "
    "were interviewed, then a reconciler folded their questions into a "
    "smaller set. Your ONLY job is to catch a whole stakeholder's "
    "concern being LOST in that folding — not to judge wording or "
    "suggest new questions.\n"
    "For EACH audience in the list below, decide whether the decisions "
    "that audience needed to raise are still answerable from the FINAL "
    "questions — either asked directly or genuinely covered by a "
    "question now owned by another profile. Mark it covered=true when "
    "its concern survives (even if folded elsewhere), and covered=false "
    "ONLY when a real, decision-changing concern it raised is now "
    "missing.\n"
    "Return ONLY a JSON object wrapped EXACTLY in <COVERAGE> and "
    "</COVERAGE> tags and nothing else, matching this shape:\n"
    '{{"audiences": [{{"audience": "infosec", "covered": false, '
    '"missing": "no question about auth for the new endpoint"}}]}}\n'
    "Do not edit any files.\n\nISSUE:\n{issue}\n\n"
    "AUDIENCES:\n{audiences}\n\n"
    "ORIGINAL POOLED QUESTIONS:\n{pool}\n\n"
    "FINAL CONSOLIDATED QUESTIONS:\n{final}"
)
GENERATION_PROMPT = (
    "You are helping refine a GitHub issue before implementation by "
    "interviewing one stakeholder profile. {persona}\n\n"
    "Read the issue and the surrounding codebase. Ask ONLY the "
    "questions this profile needs answered that are not already covered "
    "by the answers gathered so far. Output a single JSON object "
    "wrapped EXACTLY in <QUESTIONS> and </QUESTIONS> tags and nothing "
    "else, matching this shape:\n"
    '{{"questions": [{{"id": "q1", "prompt": "...", "why": "...", '
    '"type": "single_select", "required": true, '
    '"waiver_label": "Unknown / N/A", '
    '"options": [{{"value": "a", "label": "Option A"}}]}}]}}\n'
    '"type" is one of "single_select", "multi_select", "boolean", '
    '"free_text" ("options" only applies to the select types). '
    '"waiver_label" is the label offered when the answerer cannot '
    "answer and must instead record a reason — tailor it to the "
    'question (for a security trade-off, e.g. "Accept this risk"). If '
    "this profile has nothing to ask, output "
    '<QUESTIONS>{{"questions": []}}</QUESTIONS>. Do not edit any '
    "files.\n\nISSUE:\n{issue}\n\n{answers}"
)
WRITE_REFINED_PROMPT = (
    "You have finished interviewing the stakeholders about this GitHub "
    "issue. Using the issue and all the answers below, write the "
    "complete refined issue description, folding the answers into a "
    "clear, implementation-ready specification. When the answers carry "
    "effort, timeline, dependency, or capacity signals (typically from "
    "the PM or engineering), add a dedicated '## Effort & timeline' "
    "section near the end of the issue with a rough estimate and the "
    "assumptions behind it; omit that section entirely when there is "
    "nothing to estimate. Output ONLY the refined "
    "issue wrapped EXACTLY in <REFINED_ISSUE> and </REFINED_ISSUE> tags "
    "and nothing else. Do not edit any files.\n\nISSUE:\n{issue}\n\n"
    "{answers}"
)
REFINE_FEEDBACK_PROMPT = (
    "The refined issue below was not approved. Revise it according to "
    "the feedback. Preserve any '## Assumptions & accepted risks' "
    "section unless the feedback changes it. Output ONLY the revised "
    "issue wrapped EXACTLY in <REFINED_ISSUE> and </REFINED_ISSUE> tags "
    "and nothing else.\n\nCURRENT REFINED ISSUE:\n{current}\n\n"
    "FEEDBACK:\n{feedback}"
)
PLAN_FEEDBACK_PROMPT = (
    "The plan was not approved. Revise it according to this feedback and "
    "output the complete revised plan wrapped EXACTLY in <PLAN> and "
    "</PLAN> tags and nothing else. Do not edit any files.\n\n"
    "FEEDBACK:\n{feedback}"
)
IMPLEMENT_FEEDBACK_PROMPT = (
    "The implementation was not approved. Address this feedback by "
    "editing the repository now.\n\nFEEDBACK:\n{feedback}"
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
    "Implement the plan you just produced. Make all necessary code "
    "edits in this repository now. If you get genuinely blocked and "
    "need a decision you cannot make yourself, ask ONE round of "
    "clarifying questions as a single JSON object wrapped EXACTLY in "
    "<QUESTIONS> and </QUESTIONS> tags and nothing else, matching "
    "this shape:\n"
    '{"questions": [{"id": "q1", "prompt": "...", "why": "...", '
    '"type": "single_select", "required": true, '
    '"options": [{"value": "a", "label": "Option A"}]}]}\n'
    '"type" is one of "single_select", "multi_select", "boolean", '
    '"free_text" ("options" only applies to the select types; omit '
    "it otherwise). Otherwise, once the implementation is complete, "
    "just stop — do not wrap your final summary in any tags."
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
    refinement: str | None = None


def _failure_reason(exc: BaseException) -> str:
    """A concise reason from a failed generator turn, for chip + gate.

    The backend's own errors already read well ("LLM request … timed out
    after 120s (model 'llama3')"); fall back to the type name and cap the
    length so it fits a chip.
    """
    message = str(exc).strip() or type(exc).__name__
    return message if len(message) <= 200 else message[:197] + "…"


def _bind(step: WorkflowStep, slot: StepSession) -> Callable[[str], None]:
    """Return an on_session_id callback that records the resolved id on
    both the step's chip slot and its primary session pointer."""

    def _on(sid: str) -> None:
        slot.session_id = sid
        step.session_id = sid

    return _on


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
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.workflows = workflows
        self.backends = backends
        self.git = git
        self.github = github
        self.notifier = notifier
        self.bus = bus
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

    def _new_control(self) -> _Control:
        loop = asyncio.get_running_loop()
        return _Control(gate=loop.create_future(), replies=asyncio.Queue())

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
        self.workflows.save(run)
        self.notifier.notify(run)
        if self.bus is not None:
            # Tick every SSE subscriber so the UI re-reads this run
            # (state, chips, deliverable) instead of polling.
            self.bus.publish(run.id)

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
        self._spawn_driver(run.id, self._drive(run.id))
        return run.id

    def _awaiting_input_step(self, run: WorkflowRun) -> WorkflowStep:
        """
        Return whichever step is currently awaiting a reply.

        :param run: The run to search.
        :returns: The step with status "awaiting_input".
        :raises InvalidWorkflowStateError: If no step is awaiting
            input.
        """
        for step in run.steps:
            if step.status == "awaiting_input":
                return step
        raise InvalidWorkflowStateError("not awaiting a reply")

    def reply(self, workflow_id: str, text: str) -> None:
        run = self.get(workflow_id)
        step = self._awaiting_input_step(run)
        if step.name == "refine":
            # The refine interview is always structured now; only the
            # implement blocker still accepts a free-text reply.
            raise InvalidWorkflowStateError(
                "this interview expects structured answers; use /answers"
            )
        self._control[workflow_id].replies.put_nowait(text)

    def _interview_state(
        self, workflow_id: str
    ) -> tuple[WorkflowRun, WorkflowStep, InterviewEnvelope]:
        """Return the run/step/envelope for a pending refine interview.

        :raises InvalidWorkflowStateError: If the refine step is not
            currently awaiting structured answers.
        """
        run = self.get(workflow_id)
        step = run.steps[0]
        if step.name != "refine" or step.status != "awaiting_input":
            raise InvalidWorkflowStateError("not awaiting a refine reply")
        envelope = parse_envelope(step.deliverable or "")
        if envelope is None:
            raise InvalidWorkflowStateError("no pending questionnaire")
        return run, step, envelope

    def save_draft(
        self, workflow_id: str, answers: dict[str, object]
    ) -> None:
        """
        Persist a partial answer set without finalizing the interview.

        Answers may be incomplete, so only well-formedness is checked —
        never completeness — and the agent is not resumed. The draft is
        stored in the interview envelope so it survives a reload.

        :param workflow_id: Id of the run being answered.
        :param answers: Question id -> submitted value or waiver.
        :raises InvalidWorkflowStateError: If no interview is pending.
        :raises AnswerValidationError: If a provided answer is malformed.
        """
        run, step, envelope = self._interview_state(workflow_id)
        validate_answers(envelope.questionnaire, answers, partial=True)
        envelope.draft_answers = answers
        step.deliverable = build_envelope(envelope)
        # A draft save does not change status, so persist directly
        # rather than through _save (which would re-run the notifier).
        self.workflows.save(run)

    def submit_answers(
        self, workflow_id: str, answers: dict[str, object]
    ) -> None:
        """
        Answer whichever step's pending structured questionnaire.

        The refine interview carries a persisted envelope and is resumed
        with the raw answers (which its loop folds into the accumulated
        Q&A); the implement blocker uses the simpler bare questionnaire
        and is resumed with the formatted answer text ``reply`` uses.

        :param workflow_id: Id of the run being answered.
        :param answers: Question id -> submitted value or waiver.
        :raises InvalidWorkflowStateError: If no step is awaiting
            input, or it has no pending questionnaire.
        :raises AnswerValidationError: If any answer is invalid.
        """
        run = self.get(workflow_id)
        step = self._awaiting_input_step(run)
        if step.name == "refine":
            envelope = parse_envelope(step.deliverable or "")
            if envelope is None:
                raise InvalidWorkflowStateError("no pending questionnaire")
            validate_answers(envelope.questionnaire, answers)
            self._control[workflow_id].replies.put_nowait(answers)
            return
        questionnaire = parse_questionnaire_json(step.deliverable or "")
        if questionnaire is None:
            raise InvalidWorkflowStateError("no pending questionnaire")
        validate_answers(questionnaire, answers)
        prompt = format_answers(questionnaire, answers)
        self._control[workflow_id].replies.put_nowait(prompt)

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
        # Only an approval gate accepts approve/reject. Guarding on the
        # run's phase (not gate.done()) closes the window between gates
        # where a fresh, not-yet-awaited future would be pre-armed.
        if not run.status.endswith("_approval"):
            raise InvalidWorkflowStateError("no gate awaiting a decision")
        self._control[workflow_id].gate.set_result(decision)

    async def delete(self, workflow_id: str) -> None:
        """
        Abandon a run: cancel it and drop every trace of its local work.

        Cancels the driver task, then terminates and deletes every session
        that ran in the run's workspace (the coordinator, each specialist,
        plan, implement) — killing any in-flight subprocess and dropping
        the session's records, not just the latest one a step still points
        at. Forgets the control state, removes the registry record and its
        persisted rows, and deletes the cloned workspace. Deliberately
        never touches GitHub — abandoning drops work only, it does not
        close issues, comment, or open/close PRs.

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
        if run.workspace:
            shutil.rmtree(run.workspace, ignore_errors=True)

    # ---- orchestration -------------------------------------------------
    async def _await_gate(self, workflow_id: str) -> _Decision:
        control = self._control[workflow_id]
        decision = await control.gate
        control.gate = asyncio.get_running_loop().create_future()
        return decision

    async def recover(self) -> None:
        """
        Resume persisted runs after a process restart.

        Gate-parked runs (awaiting input or approval) get a
        fresh control and a driver task that re-enters at the
        gate. Runs that died mid-step are failed loudly —
        their subprocess is gone.
        """
        for run in self.workflows.list():
            if run.status.startswith("awaiting_"):
                self._control[run.id] = self._new_control()
                self._spawn_driver(run.id, self._resume(run.id))
            elif run.status in _TRANSIENT:
                run.status = "failed"
                run.error = "backend restarted mid-step"
                self._save(run)

    async def _resume(self, workflow_id: str) -> None:
        """Re-enter a gate-parked run after recovery."""
        run = self.get(workflow_id)
        try:
            await self._continue(run)
        except _Rejected:
            run.status = "rejected"
            self._save(run)
        except Exception as exc:
            _logger.exception(
                "workflow %s (%s#%s) failed during %s",
                workflow_id, run.repo, run.issue_number,
                run.status,
            )
            run.status = "failed"
            run.error = str(exc)
            self._save(run)

    async def _drive(self, workflow_id: str) -> None:
        run = self.get(workflow_id)
        try:
            run.status = "cloning"
            self._save(run)
            issue = await self.github.get_issue(run.repo, run.issue_number)
            run.issue_title = issue.title
            run.base_branch = await self.github.get_default_branch(run.repo)
            self._save(run)
            remote = f"{self.settings.git_base}/{run.repo}.git"
            await self.git.clone(remote, run.workspace)
            await self.git.checkout_branch(run.workspace, run.branch)

            if has_sentinel(issue.body):
                run.steps[0].status = "done"
                run.steps[0].deliverable = issue.body
                self._save(run)
                await self._continue(run)
            else:
                await self._continue(run, issue_body=issue.body)
        except _Rejected:
            run.status = "rejected"
            self._save(run)
        except Exception as exc:  # record, do not crash the loop
            _logger.exception(
                "workflow %s (%s#%s) failed during %s",
                workflow_id, run.repo, run.issue_number, run.status,
            )
            run.status = "failed"
            run.error = str(exc)
            self._save(run)

    async def _continue(
        self, run: WorkflowRun, issue_body: str | None = None
    ) -> None:
        """Run every unfinished phase, then deliver."""
        if run.steps[0].status != "done":
            await self._refine(run, issue_body)
        if run.steps[1].status != "done":
            await self._plan(run)
        if run.steps[2].status != "done":
            await self._implement(run)
        await self._deliver(run)

    async def _refine(
        self, run: WorkflowRun, body: str | None = None
    ) -> None:
        """Drive the profile-aware refinement interview to an approved,
        refined issue.

        A coordinator picks the stakeholder profiles to interview each
        round; one sub-agent per profile (carrying that profile's
        persona) generates its questions; the human answers (with
        partial saves and waivers); the coordinator may open further
        rounds. A writer then folds every answer into the refined issue,
        to which the deterministic risk section is appended before the
        approval gate.
        """
        step = run.steps[0]
        step.model = get_policy().model_for("refine")
        if step.status != "awaiting_approval":
            issue, accumulated = await self._run_interview(run, body)
            step.deliverable = await self._write_refined(
                run, issue, accumulated
            )
            step.active_sessions = []  # chips off at the gate
            step.status = "awaiting_approval"
            run.status = "awaiting_refine_approval"
            self._save(run)
        while True:
            decision = await self._await_gate(run.id)
            if decision.approved:
                final = decision.deliverable or (step.deliverable or "")
                await self.github.update_issue(
                    run.repo, run.issue_number, append_sentinel(final),
                )
                step.deliverable = final
                step.status = "done"
                self._save(run)
                return
            if decision.refinement is None:
                raise _Rejected()
            step.deliverable = await self._rewrite_refined(
                run, step.deliverable or "", decision.refinement
            )
            step.active_sessions = []  # chips off at the gate
            step.status = "awaiting_approval"
            run.status = "awaiting_refine_approval"
            self._save(run)

    async def _run_interview(
        self, run: WorkflowRun, body: str | None
    ) -> tuple[str, list[QAEntry]]:
        """Run coordinator-driven interview rounds until done.

        :returns: The issue text and the accumulated Q&A entries.
        """
        step = run.steps[0]
        if step.status == "awaiting_input":
            # Recovered mid-interview: rebuild loop state from the
            # persisted envelope and consume the pending finalize.
            envelope = parse_envelope(step.deliverable or "")
            if envelope is None:
                raise InvalidWorkflowStateError("interview state lost")
            issue = envelope.issue
            accumulated = list(envelope.accumulated)
            round_no = step.refine_round
            answers = await self._control[run.id].replies.get()
            accumulated += to_entries(envelope.questionnaire, answers)
            round_no += 1
        else:
            if body is None:
                raise InvalidWorkflowStateError(
                    "fresh refine needs the issue body"
                )
            issue = body
            accumulated = []
            round_no = 1

        while round_no <= MAX_REFINE_ROUNDS:
            run.status = "refining"
            step.status = "running"
            self._save(run)
            profiles = await self._coordinator_profiles(
                run, issue, accumulated
            )
            if not profiles:
                break
            questionnaire = await self._generate_questions(
                run, issue, accumulated, profiles
            )
            if not questionnaire.questions:
                break
            step.refine_round = round_no
            step.deliverable = build_envelope(
                InterviewEnvelope(
                    questionnaire=questionnaire,
                    draft_answers={},
                    accumulated=accumulated,
                    issue=issue,
                )
            )
            step.active_sessions = []  # human's turn: chips off
            step.status = "awaiting_input"
            run.status = "awaiting_refine_input"
            self._save(run)
            answers = await self._control[run.id].replies.get()
            accumulated += to_entries(questionnaire, answers)
            round_no += 1
        return issue, accumulated

    def _show_sessions(
        self, run: WorkflowRun, slots: list[StepSession]
    ) -> None:
        """Publish the sessions active on the refine step right now.

        Each ``_save`` pushes the chip state to the UI (via the poll
        today, the SSE stream in a later phase). The slots are the
        ephemeral, non-persisted telemetry the workflow view animates.
        """
        run.steps[0].active_sessions = slots
        self._save(run)

    def _watch_activity(
        self, run: WorkflowRun, session_id: str, slot: StepSession
    ) -> asyncio.Task:
        """Track a session's live activity onto its chip.

        Subscribes to the session's canonical event stream and maps each
        event to a 1-2 word activity (:func:`activity_for`), updating the
        chip and re-publishing the run **only when the word changes** — so
        a chatty stream costs a handful of SSE ticks, not one per event.
        Returns the monitor task; the caller cancels it when the turn ends.
        """
        # Subscribe synchronously (before the task is scheduled) so no
        # event slips through between session-id resolution and the
        # monitor first running.
        queue = self.sessions.subscribe(session_id)

        async def _watch() -> None:
            try:
                while True:
                    event = await queue.get()
                    word = activity_for(event)
                    if word is not None and word != slot.activity:
                        slot.activity = word
                        self._save(run)
            finally:
                self.sessions.unsubscribe(session_id, queue)

        return asyncio.create_task(_watch())

    async def _run_turn_tracked(
        self,
        run: WorkflowRun,
        backend: Backend,
        req: TurnRequest,
        slot: StepSession,
        bind: Callable[[str], None],
    ) -> TurnResult:
        """Run one turn while streaming its live activity onto the chip.

        Wraps *bind* (the existing ``on_session_id`` that records the
        session id) so that, once the id is known, a :meth:`_watch_activity`
        monitor starts; it is always cancelled and the activity cleared
        when the turn finishes, however it finishes.
        """
        monitor: asyncio.Task | None = None

        def _on_sid(session_id: str) -> None:
            nonlocal monitor
            bind(session_id)
            monitor = self._watch_activity(run, session_id, slot)

        try:
            return await backend.run_turn(req, on_session_id=_on_sid)
        finally:
            if monitor is not None:
                monitor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor
            slot.activity = None

    async def _run_refine_agent(
        self,
        run: WorkflowRun,
        prompt: str,
        slot: StepSession,
        substep: str = "refine",
    ) -> str:
        """Run one stateless refine sub-agent, tracking its own session.

        Each call is a fresh (non-resumed) read-only session. It fills in
        its own *slot* — so concurrent generators never race on a single
        shared field — and marks it idle when done; ``step.session_id``
        still tracks the latest for back-compat.

        *substep* is a dotted policy key (e.g. ``"refine.reconcile"``) so
        a deployment can route just one sub-agent — most usefully the
        reconciler — to a stronger backend/model; it falls back to the
        ``refine`` step's backend and model when unconfigured.
        """
        step = run.steps[0]

        def _bind(s: str) -> None:
            slot.session_id = s
            step.session_id = s

        backend = self.backends.backend_for(substep)
        result = await self._run_turn_tracked(
            run,
            backend,
            TurnRequest(
                prompt=prompt, cwd=run.workspace,
                permission_mode="plan",
                model=get_policy().model_for(substep),
            ),
            slot,
            _bind,
        )
        slot.status = "idle"
        return result.final_text

    async def _coordinator_profiles(
        self, run: WorkflowRun, issue: str, accumulated: list[QAEntry]
    ) -> list[str]:
        """Ask the coordinator which profiles to interview next.

        With ``refine_samples > 1`` the coordinator is polled several
        times and the picks are UNIONed (first-seen order preserved):
        a weak model that intermittently forgets a specialist still
        summons it if any sample does. A failed sample is skipped, not
        fatal. K=1 is exactly one call, as before.
        """
        samples = max(1, self.settings.refine_samples)
        slots = [
            StepSession(
                profile_id="coordinator", label="Coordinator", badge="sys"
            )
            for _ in range(samples)
        ]
        self._show_sessions(run, slots)

        async def _one(slot: StepSession) -> list[str]:
            text = await self._run_refine_agent(
                run,
                COORDINATOR_PROMPT.format(
                    roster=roster_summary(),
                    issue=issue,
                    answers=render_qa(accumulated),
                ),
                slot,
                substep="refine.coordinator",
            )
            return [pid for pid in (extract_profiles(text) or []) if pid]

        picks = await asyncio.gather(
            *(_one(slot) for slot in slots), return_exceptions=True
        )
        ordered: list[str] = []
        for result in picks:
            if isinstance(result, BaseException):
                _logger.warning("coordinator sample failed: %r", result)
                continue
            for pid in result:
                if pid not in ordered:
                    ordered.append(pid)
        return ordered

    async def _generate_questions(
        self,
        run: WorkflowRun,
        issue: str,
        accumulated: list[QAEntry],
        profile_ids: list[str],
    ) -> Questionnaire:
        """Fan out to one generator per profile, concurrently, and
        aggregate their questions.

        Every selected profile is interviewed at the same time — each in
        its own live session with its own activity chip — so the user
        sees the whole panel working at once. Each question's audience is
        stamped from its generating profile and its id namespaced by
        profile, so ids stay unique across the aggregated set.
        """
        # Dedup while preserving the coordinator's ordering, so a profile
        # named twice does not run twice or collide on namespaced ids.
        ordered: list[str] = []
        for pid in profile_ids:
            if pid not in ordered:
                ordered.append(pid)
        profiles_by_id = {pid: get_profile(pid) for pid in ordered}
        slots = {
            pid: StepSession(
                profile_id=p.id, label=p.label, badge=p.badge
            )
            for pid, p in profiles_by_id.items()
        }
        self._show_sessions(run, list(slots.values()))

        samples = max(1, self.settings.refine_samples)

        async def _one(
            pid: str,
        ) -> tuple[str, list[Questionnaire | None]]:
            profile = profiles_by_id[pid]

            async def _sample() -> Questionnaire | None:
                text = await self._run_refine_agent(
                    run,
                    GENERATION_PROMPT.format(
                        persona=profile.system_prompt,
                        issue=issue,
                        answers=render_qa(accumulated),
                    ),
                    slots[pid],
                    substep="refine.generate",
                )
                return extract_questionnaire(text)

            # Draw ``samples`` questionnaires from this profile (K=1 is
            # one draw, as before). A flaky sample is dropped; the
            # profile only fails when every draw failed.
            drawn = await asyncio.gather(
                *(_sample() for _ in range(samples)),
                return_exceptions=True,
            )
            kept: list[Questionnaire | None] = []
            errors: list[BaseException] = []
            for outcome in drawn:
                if isinstance(outcome, BaseException):
                    errors.append(outcome)
                else:
                    kept.append(outcome)
            if errors and not kept:
                raise errors[0]
            return pid, kept

        # One specialist failing (e.g. a flaky/slow local LLM timing out)
        # must not sink the whole panel: collect per-profile results, mark
        # a failed profile's chip and drop it, and only fail the step if
        # every profile failed (leaving nothing to ask).
        raw = await asyncio.gather(
            *(_one(pid) for pid in ordered), return_exceptions=True
        )
        results: list[tuple[str, list[Questionnaire | None]]] = []
        failures: list[tuple[str, BaseException]] = []
        issues: list[GenerationIssue] = []
        for pid, outcome in zip(ordered, raw):
            if isinstance(outcome, Exception):
                reason = _failure_reason(outcome)
                slots[pid].status = "error"
                slots[pid].error = reason
                failures.append((pid, outcome))
                issues.append(GenerationIssue(
                    profile=pid, label=slots[pid].label, reason=reason
                ))
                _logger.warning("refine profile %s failed: %s", pid, reason)
            else:
                results.append(outcome)
        # A profile that returned but parsed to no questionnaire (empty or
        # garbled output) is a silent failure: it contributes nothing yet
        # its chip would otherwise read "idle". Flag it too. A valid but
        # empty questionnaire (nothing to ask) is not a failure.
        for pid, questionnaires in results:
            if any(q is not None for q in questionnaires):
                continue
            reason = "no response (empty or unparseable output)"
            slots[pid].status = "error"
            slots[pid].error = reason
            issues.append(GenerationIssue(
                profile=pid, label=slots[pid].label, reason=reason
            ))
            _logger.warning(
                "refine profile %s produced no questionnaire", pid
            )
        if issues:
            self._show_sessions(run, list(slots.values()))
        if failures and not results:
            detail = ", ".join(
                f"{pid} ({type(exc).__name__}: {exc})" or pid
                for pid, exc in failures
            )
            raise RuntimeError(f"all specialist interviews failed: {detail}")

        questions: list[Question] = []
        for pid, questionnaires in results:
            profile = profiles_by_id[pid]
            for sample_index, questionnaire in enumerate(questionnaires):
                if questionnaire is None:
                    continue
                for question in questionnaire.questions:
                    question.audience = profile.id
                    # Namespace by profile so ids stay unique; add a
                    # sample tag only when ensembling, so K=1 keeps the
                    # historical ``profile:qid`` form.
                    tag = f"s{sample_index}:" if samples > 1 else ""
                    question.id = f"{profile.id}:{tag}{question.id}"
                    questions.append(question)

        # Within-round consolidation. The generators (and, under
        # ensembling, repeated draws) run blind to one another, so the
        # pool can hold the same decision several times over.
        # ``reconcile_mode`` chooses how hard to consolidate:
        #   - ``rewrite``: the LLM reconciler authors a fresh minimal set
        #     (only worthwhile when >1 audience and >1 question);
        #   - ``dedup``: deterministic within-audience duplicate removal,
        #     coverage-safe on weak models that over-prune;
        #   - ``off``: keep the pool untouched.
        mode = self.settings.reconcile_mode
        if mode == "dedup":
            if len(questions) > 1:
                questions = self._dedup_questions(questions)
        elif mode == "rewrite":
            audiences = {q.audience for q in questions}
            if len(audiences) > 1 and len(questions) > 1:
                questions = await self._reconcile_questions(
                    run, issue, questions
                )

        # Rebuild the profile metadata from the *kept* questions, so a
        # profile whose only question the reconciler dropped no longer
        # yields an (empty) tab in the interview.
        profiles: dict[str, ProfileMeta] = {}
        for question in questions:
            if question.audience in profiles:
                continue
            profile = profiles_by_id[question.audience]
            profiles[question.audience] = ProfileMeta(
                id=profile.id, label=profile.label, badge=profile.badge
            )
        return Questionnaire(
            questions=questions, profiles=list(profiles.values()),
            issues=issues,
        )

    def _dedup_questions(self, questions: list[Question]) -> list[Question]:
        """Coverage-safe, LLM-free consolidation for ``reconcile_mode`` =
        ``dedup``.

        Drops only exact within-audience prompt duplicates (as ensembling
        the same profile tends to produce), never folding across
        audiences — so unlike the rewriter it cannot lose a domain. Ids
        are re-namespaced to stay unique and stable.
        """
        seen: set[tuple[str, str]] = set()
        kept: list[Question] = []
        for question in questions:
            key = (
                question.audience,
                " ".join(question.prompt.lower().split()),
            )
            if key in seen:
                continue
            seen.add(key)
            kept.append(question)
        for index, question in enumerate(kept):
            question.id = f"{question.audience}:d{index}"
        return kept

    async def _reconcile_questions(
        self, run: WorkflowRun, issue: str, questions: list[Question]
    ) -> list[Question]:
        """Consolidate the pooled questions via a reconciler agent.

        The concurrent generators run blind to one another, so two
        profiles can ask essentially the same question with different
        framings (e.g. Product's scope-framed and Eng's mechanism-framed
        "how are accounts created?"). A reconciler sub-agent — shown as
        one more chip — authors a fresh, minimal, plainly-phrased set:
        it folds overlaps into one question, assigns each to the single
        owning specialist, and keeps Product's questions the simplest.

        Reconciliation may only ever *improve* the pool, never blank or
        corrupt it: the rewritten set is accepted only when it parses,
        is non-empty, and every question has a pool audience and (for
        select types) real options. On top of that, a **coverage
        invariant** refuses any rewrite that drops a whole summoned
        audience without explicitly folding its questions elsewhere
        (weak models over-prune) — so no domain is silently lost. Any
        anomaly falls back to the untouched pool. When ``refine_critic``
        is on, a completeness critic then re-checks the survivors.

        :param run: The run whose interview is being reconciled.
        :param issue: The issue text, for the reconciler's context.
        :param questions: The pooled, namespaced questions to dedup.
        :returns: The consolidated questions, or the pool on fallback.
        """
        slot = StepSession(
            profile_id="reconciler", label="Reconciler", badge="sys"
        )
        self._show_sessions(run, [slot])
        payload = json.dumps(
            [
                {
                    "id": q.id,
                    "audience": q.audience,
                    "prompt": q.prompt,
                    "why": q.why,
                    "type": q.type,
                    "required": q.required,
                    "waiver_label": q.waiver_label,
                    "options": [
                        {"value": o.value, "label": o.label}
                        for o in q.options
                    ],
                }
                for q in questions
            ]
        )
        text = await self._run_refine_agent(
            run,
            RECONCILE_PROMPT.format(
                issue=issue, questions=payload, roster=roster_summary()
            ),
            slot,
            substep="refine.reconcile",
        )
        reconciled = extract_questionnaire(text)
        if reconciled is None or not reconciled.questions:
            return questions
        pool_audiences = {q.audience for q in questions}
        rebuilt: list[Question] = []
        declared_folded: set[str] = set()
        for index, question in enumerate(reconciled.questions):
            if question.audience not in pool_audiences:
                return questions  # unknown owner: unsafe, keep the pool
            if question.type in ("single_select", "multi_select") and (
                not question.options
            ):
                return questions  # unanswerable select: keep the pool
            declared_folded.update(question.folded_from)
            question.id = f"{question.audience}:r{index}"
            rebuilt.append(question)
        if not rebuilt:
            return questions
        # Coverage invariant: a summoned audience may vanish from the
        # rewrite ONLY if every one of its pooled questions was declared
        # folded into a surviving question. An audience that disappears
        # with its folds undeclared is the weak-model failure this guards
        # against — keep the full pool so no domain is silently dropped.
        surviving = {q.audience for q in rebuilt}
        pooled_ids: dict[str, list[str]] = {}
        for pooled in questions:
            pooled_ids.setdefault(pooled.audience, []).append(pooled.id)
        for audience, ids in pooled_ids.items():
            if audience in surviving:
                continue
            if not all(qid in declared_folded for qid in ids):
                return questions  # silent domain drop: keep the pool
        # A declared fold can still hide a softened-away concern; the
        # completeness critic (when enabled) re-injects any it catches.
        if self.settings.refine_critic:
            rebuilt = await self._critique_coverage(
                run, issue, questions, rebuilt
            )
        return rebuilt

    async def _critique_coverage(
        self,
        run: WorkflowRun,
        issue: str,
        pool: list[Question],
        reconciled: list[Question],
    ) -> list[Question]:
        """Adversarial completeness pass over a reconciled set.

        Asks a critic, per summoned audience, whether that audience's
        concern still survives the fold. Any audience it marks uncovered
        has its original pooled questions deterministically re-injected —
        cheaper and safer than a second generative round, which on a weak
        model risks dropping something else. Best-effort: an absent or
        garbled verdict leaves the set unchanged (M1 already guarantees
        no *silent* drop reached this point).
        """
        slot = StepSession(
            profile_id="critic", label="Critic", badge="sys"
        )
        self._show_sessions(run, [slot])
        pool_audiences = {q.audience for q in pool}

        def _payload(items: list[Question]) -> str:
            return json.dumps(
                [
                    {"id": q.id, "audience": q.audience,
                     "prompt": q.prompt, "why": q.why}
                    for q in items
                ]
            )

        text = await self._run_refine_agent(
            run,
            CRITIC_PROMPT.format(
                issue=issue,
                audiences=json.dumps(sorted(pool_audiences)),
                pool=_payload(pool),
                final=_payload(reconciled),
            ),
            slot,
            substep="refine.critic",
        )
        verdict = extract_coverage(text)
        if not verdict:
            return reconciled
        uncovered = {
            audience
            for audience, covered in verdict.items()
            if not covered and audience in pool_audiences
        }
        if not uncovered:
            return reconciled
        # Re-inject the flagged audiences' original questions,
        # renamespaced so ids stay unique against the reconciled set.
        result = list(reconciled)
        dropped = [q for q in pool if q.audience in uncovered]
        for offset, question in enumerate(dropped):
            question.id = f"{question.audience}:c{offset}"
            result.append(question)
        _logger.info(
            "critic re-injected dropped audiences: %s",
            ", ".join(sorted(uncovered)),
        )
        return result

    async def _write_refined(
        self, run: WorkflowRun, issue: str, accumulated: list[QAEntry]
    ) -> str:
        """Write the refined issue and append the risk section."""
        slot = StepSession(
            profile_id="writer", label="Writer", badge="agent"
        )
        self._show_sessions(run, [slot])
        text = await self._run_refine_agent(
            run,
            WRITE_REFINED_PROMPT.format(
                issue=issue, answers=render_qa(accumulated)
            ),
            slot,
        )
        body = extract_refined_issue(text) or text
        risks = render_assumptions_and_risks(accumulated)
        if risks:
            body = f"{body.rstrip()}\n\n{risks}"
        return body

    async def _rewrite_refined(
        self, run: WorkflowRun, current: str, feedback: str
    ) -> str:
        """Regenerate the refined issue from gate feedback."""
        slot = StepSession(
            profile_id="writer", label="Writer", badge="agent"
        )
        self._show_sessions(run, [slot])
        text = await self._run_refine_agent(
            run,
            REFINE_FEEDBACK_PROMPT.format(
                current=current, feedback=feedback
            ),
            slot,
        )
        return extract_refined_issue(text) or text

    async def _plan(self, run: WorkflowRun) -> None:
        step = run.steps[1]
        refined = run.steps[0].deliverable or ""
        prompt: str | None
        if step.status == "awaiting_approval":
            prompt = None  # recovered at the gate: skip to it
        else:
            prompt = PLAN_PROMPT.format(issue=refined)
        model = get_policy().model_for("plan")
        step.model = model
        while True:
            if prompt is not None:
                run.status = "planning"
                step.status = "running"
                slot = StepSession(
                    profile_id="planner", label="Planner", badge="agent"
                )
                step.active_sessions = [slot]
                self._save(run)
                result = await self._run_turn_tracked(
                    run,
                    self.backends.backend_for("plan"),
                    TurnRequest(
                        prompt=prompt, cwd=run.workspace,
                        permission_mode="plan",
                        model=model, resume_id=step.session_id,
                    ),
                    slot,
                    _bind(step, slot),
                )
                text = result.final_text
                # Prefer the tagged block; fall back to the raw
                # text so a run still gets a reviewable
                # deliverable if the model doesn't comply (e.g.
                # it falls into its native Plan Mode and tries
                # ExitPlanMode instead).
                step.deliverable = extract_plan(text) or text
                step.active_sessions = []
                step.status = "awaiting_approval"
                run.status = "awaiting_plan_approval"
                self._save(run)
            decision = await self._await_gate(run.id)
            if decision.approved:
                step.status = "done"
                self._save(run)
                # implement resumes this plan session via
                # run.steps[1].session_id.
                return
            if decision.refinement is None:
                raise _Rejected()
            prompt = PLAN_FEEDBACK_PROMPT.format(
                feedback=decision.refinement
            )

    async def _implement(self, run: WorkflowRun) -> None:
        step = run.steps[2]
        prompt: str | None
        if step.status == "awaiting_approval":
            prompt = None  # recovered at the gate: skip to it
        elif step.status == "awaiting_input":
            # Recovered mid-blocker: wait for the answer, then
            # resume the persisted claude session with it.
            prompt = await self._control[run.id].replies.get()
        else:
            prompt = IMPLEMENT_PROMPT
        model = get_policy().model_for("implement")
        step.model = model
        while True:
            if prompt is not None:
                run.status = "implementing"
                step.status = "running"
                slot = StepSession(
                    profile_id="builder", label="Builder", badge="agent"
                )
                step.active_sessions = [slot]
                self._save(run)
                result = await self._run_turn_tracked(
                    run,
                    self.backends.backend_for("implement"),
                    TurnRequest(
                        prompt=prompt, cwd=run.workspace,
                        permission_mode="acceptEdits",
                        model=model,
                        resume_id=(
                            step.session_id
                            or run.steps[1].session_id
                        ),
                    ),
                    slot,
                    _bind(step, slot),
                )
                text = result.final_text
                diff = await self.git.diff(run.workspace)
                if not diff.strip():
                    # No changes yet: treat the response as a
                    # blocker, structured or raw-text.
                    questionnaire = extract_questionnaire(text)
                    step.deliverable = (
                        questionnaire.model_dump_json()
                        if questionnaire is not None
                        else text
                    )
                    step.active_sessions = []  # human's turn: chips off
                    step.status = "awaiting_input"
                    run.status = "awaiting_implement_input"
                    self._save(run)
                    prompt = await (
                        self._control[run.id].replies.get()
                    )
                    continue
                step.deliverable = diff
                step.active_sessions = []  # chips off at the gate
                step.status = "awaiting_approval"
                run.status = "awaiting_implement_approval"
                self._save(run)
            decision = await self._await_gate(run.id)
            if decision.approved:
                step.status = "done"
                self._save(run)
                return
            if decision.refinement is None:
                raise _Rejected()
            prompt = IMPLEMENT_FEEDBACK_PROMPT.format(
                feedback=decision.refinement
            )

    async def _deliver(self, run: WorkflowRun) -> None:
        """Commit, push, open the PR, and finish the run."""
        run.status = "opening_pr"
        self._save(run)
        await self.git.commit_all(
            run.workspace, f"Implement #{run.issue_number}"
        )
        await self.git.push(run.workspace, run.branch)
        run.pr_url = await self.github.create_pull_request(
            run.repo,
            head=run.branch,
            base=run.base_branch,
            title=f"{run.issue_title} (#{run.issue_number})",
            body=f"Closes #{run.issue_number}\n\nOpened by kestrel.",
        )
        run.status = "done"
        self._save(run)


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
        backends=get_backend_policy(),
        git=GitService(settings.github_token),
        github=GitHubClient(settings.github_api_base, settings.github_token),
        notifier=InAppNotifier(
            get_notification_store(), get_notification_bus()
        ),
        bus=get_workflow_bus(),
    )

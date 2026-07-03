"""Orchestrates the GitHub issue -> code workflow over sessions."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from app.config import Settings, get_settings
from app.models_workflow import StepSession, WorkflowRun, WorkflowStep
from app.notifications import InAppNotifier, Notifier
from app.persistence.notification_store import get_notification_store
from app.storage.notification_bus import get_notification_bus
from app.policy import get_policy
from app.profiles import get_profile, roster_summary
from app.questionnaire import (
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
from app.services.runner import SessionRunner
from app.services.workflow_text import (
    append_sentinel,
    extract_kept_ids,
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
_MAX_REFINE_ROUNDS = 3

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
    "You are reconciling the clarifying questions that several "
    "stakeholder profiles independently proposed for a GitHub issue, "
    "removing duplicates before they reach the human. Because the "
    "profiles were interviewed in parallel and could not see each "
    "other's questions, two of them may ask essentially the same "
    "thing.\n"
    "Below is the pooled set of questions as JSON — each with its "
    '"id", the "audience" profile that asked it, and its "prompt" — '
    "followed by the roster describing each profile's remit.\n"
    "For each GROUP of questions that ask essentially the SAME thing, "
    "keep EXACTLY ONE: the copy whose audience is the most "
    "authoritative owner of that topic (judge from the roster — e.g. a "
    "password-hashing choice belongs to infosec over developer). Keep "
    "every question that has no overlap. Do NOT reword, merge, "
    "combine, or invent questions — only choose which existing ids to "
    "keep.\n"
    "Return ONLY a JSON array of the question ids to keep, wrapped "
    "EXACTLY in <KEEP> and </KEEP> tags and nothing else, e.g. "
    '<KEEP>["infosec:q1", "developer:q2"]</KEEP>. Do not edit any '
    "files.\n\nISSUE:\n{issue}\n\nQUESTIONS:\n{questions}\n\n"
    "ROSTER:\n{roster}"
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
        runner: SessionRunner,
        git: GitService,
        github: GitHubClient,
        notifier: Notifier,
        bus: WorkflowBus | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.workflows = workflows
        self.runner = runner
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

        Cancels the driver task, kills any in-flight step subprocess,
        forgets the control state, removes the registry record and its
        persisted rows, and deletes the cloned workspace. Deliberately
        never touches GitHub — abandoning drops work only, it does not
        close issues, comment, or open/close PRs. Underlying sessions are
        left intact.

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
        for step in run.steps:
            if step.session_id:
                self.runner.terminate(step.session_id)
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

    def _result_text(self, session_id: str) -> str:
        rec = self.sessions.get(session_id)
        if rec is None:
            return ""
        for ev in reversed(rec.events):
            if ev.type == "result":
                value = ev.raw.get("result")
                return value if isinstance(value, str) else ""
        return ""

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
            round_no = envelope.round
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

        while round_no <= _MAX_REFINE_ROUNDS:
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
            step.deliverable = build_envelope(
                InterviewEnvelope(
                    questionnaire=questionnaire,
                    draft_answers={},
                    accumulated=accumulated,
                    round=round_no,
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

    async def _run_refine_agent(
        self, run: WorkflowRun, prompt: str, slot: StepSession
    ) -> str:
        """Run one stateless refine sub-agent, tracking its own session.

        Each call is a fresh (non-resumed) read-only session. It fills in
        its own *slot* — so concurrent generators never race on a single
        shared field — and marks it idle when done; ``step.session_id``
        still tracks the latest for back-compat.
        """
        step = run.steps[0]

        def _on_sid(s: str) -> None:
            slot.session_id = s
            step.session_id = s

        sid = await self.runner.run_blocking(
            prompt, run.workspace, "plan",
            on_session_id=_on_sid,
            model=step.model,
        )
        slot.status = "idle"
        return self._result_text(sid)

    async def _coordinator_profiles(
        self, run: WorkflowRun, issue: str, accumulated: list[QAEntry]
    ) -> list[str]:
        """Ask the coordinator which profiles to interview next."""
        slot = StepSession(
            profile_id="coordinator", label="Coordinator", badge="sys"
        )
        self._show_sessions(run, [slot])
        text = await self._run_refine_agent(
            run,
            COORDINATOR_PROMPT.format(
                roster=roster_summary(),
                issue=issue,
                answers=render_qa(accumulated),
            ),
            slot,
        )
        return [pid for pid in (extract_profiles(text) or []) if pid]

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

        async def _one(pid: str) -> tuple[str, Questionnaire | None]:
            profile = profiles_by_id[pid]
            text = await self._run_refine_agent(
                run,
                GENERATION_PROMPT.format(
                    persona=profile.system_prompt,
                    issue=issue,
                    answers=render_qa(accumulated),
                ),
                slots[pid],
            )
            return pid, extract_questionnaire(text)

        results = await asyncio.gather(*(_one(pid) for pid in ordered))

        questions: list[Question] = []
        for pid, questionnaire in results:
            if questionnaire is None:
                continue
            profile = profiles_by_id[pid]
            for question in questionnaire.questions:
                question.audience = profile.id
                question.id = f"{profile.id}:{question.id}"
                questions.append(question)

        # Within-round, cross-profile dedup: the generators ran blind
        # to one another, so two profiles can independently ask
        # essentially the same thing. Reconcile only when overlap is
        # even possible — more than one audience and more than one
        # question; a single-profile round has nothing to reconcile.
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
            questions=questions, profiles=list(profiles.values())
        )

    async def _reconcile_questions(
        self, run: WorkflowRun, issue: str, questions: list[Question]
    ) -> list[Question]:
        """Drop cross-profile duplicate questions via a reconciler agent.

        The concurrent generators can each ask essentially the same
        question (e.g. a password-hashing choice from both infosec and
        developer). A reconciler sub-agent — shown as one more chip —
        decides, per overlap, which single audience owns the topic and
        returns the ids to keep; every non-overlapping question is
        kept.

        Guards mirror the extract-fallback style used elsewhere: an
        absent or malformed keep-list — or one that would drop every
        question — falls back to the full pool, so reconciliation can
        only ever trim, never blank, the interview.

        :param run: The run whose interview is being reconciled.
        :param issue: The issue text, for the reconciler's context.
        :param questions: The pooled, namespaced questions to dedup.
        :returns: The kept questions, in their original order.
        """
        slot = StepSession(
            profile_id="reconciler", label="Reconciler", badge="sys"
        )
        self._show_sessions(run, [slot])
        payload = json.dumps(
            [
                {"id": q.id, "audience": q.audience, "prompt": q.prompt}
                for q in questions
            ]
        )
        text = await self._run_refine_agent(
            run,
            RECONCILE_PROMPT.format(
                issue=issue, questions=payload, roster=roster_summary()
            ),
            slot,
        )
        kept_ids = extract_kept_ids(text)
        if kept_ids is None:
            return questions
        keep = set(kept_ids)
        filtered = [q for q in questions if q.id in keep]
        return filtered or questions

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
                sid = await self.runner.run_blocking(
                    prompt, run.workspace, "plan",
                    resume_id=step.session_id,
                    on_session_id=_bind(step, slot),
                    model=model,
                )
                text = self._result_text(sid)
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
                sid = await self.runner.run_blocking(
                    prompt, run.workspace, "acceptEdits",
                    resume_id=(
                        step.session_id
                        or run.steps[1].session_id
                    ),
                    on_session_id=_bind(step, slot),
                    model=model,
                )
                text = self._result_text(sid)
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
        runner=SessionRunner(settings, registry),
        git=GitService(settings.github_token),
        github=GitHubClient(settings.github_api_base, settings.github_token),
        notifier=InAppNotifier(
            get_notification_store(), get_notification_bus()
        ),
        bus=get_workflow_bus(),
    )

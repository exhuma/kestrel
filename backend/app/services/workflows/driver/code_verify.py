"""The autonomous coder<->verifier loop."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.backends.base import TurnRequest
from app.models_workflow import Step, StepSession, WorkflowRun
from app.policy import get_policy
from app.ports import Evidence
from app.services.workflows import artifacts, screenshots
from app.services.workflows.driver.escalate import escalate
from app.services.workflows.prompts import (
    CODE_FEEDBACK_PROMPT,
    CODE_PROMPT,
    EXPLORE_PERMISSION_MODE,
    EXPLORE_PROMPT,
    VERIFY_PROMPT,
)
from app.services.workflows.sessions import _bind
from app.services.workflows.verify import (
    _evidence_feedback,
    _parse_verdict,
    _render_verify_report,
)

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService


async def code_and_verify(service: "WorkflowService", run: WorkflowRun) -> bool:
    """Run the autonomous code<->verify loop.

    The coder implements the design; the verifier adjudicates it against
    the PRD/design, weighing evidence from running the project's checks in
    the worktree (a failing observation forces a reject — the
    failing-observation invariant). On accept the loop finishes and the run
    proceeds to deliver; on reject the coder re-runs with feedback, bounded
    by ``max_verify_iterations``; on exhaustion (or a coder that makes no
    progress) the run escalates (FR-014..FR-020).

    :returns: ``True`` if the run escalated (caller must not deliver).
    """
    code_step, verify_step = run.steps[2], run.steps[3]
    prd = run.steps[0].deliverable or ""
    design = run.steps[1].deliverable or ""
    # Ensure both handover artifacts are on disk (defensive: _design
    # wrote them earlier this drive, but this keeps code/verify correct
    # on any resume path).
    service._write_artifact(run, "prd.md", prd)
    service._write_artifact(run, "design.md", design)
    code_model = get_policy().model_for(Step.CODE)
    verify_model = get_policy().model_for(Step.VERIFY)
    # The coder always needs FILE_EDITS, so it reads the artifacts from
    # the worktree rather than carrying their full text in the prompt.
    prompt = CODE_PROMPT.format(
        prd=service._artifact_slot(Step.CODE, run, "prd.md", prd),
        design=service._artifact_slot(Step.CODE, run, "design.md", design),
    )
    # Every attempted verify round's summary, written once the loop
    # concludes as a committed audit-trail artifact (feature 005, US3)
    # — history for a human reading the PR, never read back as verify
    # input by this or any later run (FR-009).
    rounds: list[dict] = []

    def _flush_report() -> None:
        if rounds:
            service._write_artifact(
                run, "verify-report.md", _render_verify_report(rounds)
            )

    for iteration in range(max(1, service.settings.max_verify_iterations)):
        # 1-based count of verify passes entered, for the UI's
        # remaining-runs indicator on the verify chip.
        verify_step.verify_round = iteration + 1
        # ---- code (gateless) ----
        code_step.model = code_model
        run.status = "coding"
        code_step.status = "running"
        slot = StepSession(profile_id="coder", label="Coder", badge="agent")
        code_step.active_sessions = [slot]
        service._save(run)
        # The coder inherits the designer's session for context
        # continuity, but only when both steps resolve to the same
        # backend: a session id is native to the backend that minted it,
        # so handing a design backend's id (e.g. an ``llm-…`` id) to a
        # different code backend (opencode, expecting ``ses-…``) would be
        # rejected. On a cross-backend route the coder starts fresh.
        same_backend = service.backends.backend_id_for(
            Step.DESIGN
        ) == service.backends.backend_id_for(Step.CODE)
        code_resume_id = code_step.session_id or (
            run.steps[1].session_id if same_backend else None
        )
        service._debug_log(
            run, f"Round {iteration + 1} — CODE PROMPT", prompt
        )
        # Captured before the coder's turn so the round's progress can
        # be measured against it afterwards, regardless of whether the
        # coder commits its own work or leaves it uncommitted (feature
        # 006: the coder now commits each round; kestrel no longer
        # assumes it will).
        round_start_sha = await service.git.head_sha(run.workspace)
        await service._run_turn_tracked(
            run,
            service.backends.backend_for(Step.CODE),
            TurnRequest(
                prompt=prompt, cwd=run.workspace,
                permission_mode="acceptEdits", model=code_model,
                resume_id=code_resume_id,
            ),
            slot,
            _bind(code_step, slot),
        )
        code_step.active_sessions = []
        # Exclude the handover artifacts: they are committed with the
        # change, but must not pollute what the escalation check weighs.
        # A single-ref diff against round_start_sha captures both any
        # commit(s) the coder made this round and anything it left
        # uncommitted.
        round_diff = await service.git.diff(
            run.workspace, exclude=artifacts.ARTIFACT_ROOT, ref=round_start_sha
        )
        diff_stat = await service.git.diff_stat(
            run.workspace, exclude=artifacts.ARTIFACT_ROOT, ref=round_start_sha
        )
        service._debug_log(
            run, f"Round {iteration + 1} — CODE RESULT (diff --stat)",
            diff_stat or "(empty diff)",
        )
        if not round_diff.strip():
            # A coder that cannot make progress escalates instead of
            # parking on a human gate (FR-020).
            _flush_report()
            return await escalate(
                service, run, "the coder produced no changes"
            )
        # Safety-net commit: never blindly trust the coder to have
        # committed its own work (or all of it) — if the tree is still
        # dirty, kestrel commits on its behalf so verify always
        # inspects a stable, committed tree regardless of model
        # compliance.
        still_dirty = await service.git.diff(
            run.workspace, exclude=artifacts.ARTIFACT_ROOT
        )
        if still_dirty.strip():
            await service.git.commit_all(
                run.workspace,
                f"Auto-commit (round {iteration + 1}): coder did not "
                "commit its own changes",
            )
        # The operator-facing deliverable is the cumulative diff since
        # the run's branch point, regardless of how many WIP commits
        # happened in between.
        code_step.deliverable = await service.git.diff(
            run.workspace, exclude=artifacts.ARTIFACT_ROOT, ref=run.base_branch
        )
        code_step.status = "done"
        service._save(run)

        # ---- verify (gateless, evidence-grounded) ----
        verify_step.model = verify_model
        run.status = "verifying"
        verify_step.status = "running"
        verify_slot = StepSession(
            profile_id="verifier", label="Verifier", badge="agent"
        )
        verify_step.active_sessions = [verify_slot]
        service._save(run)
        # Evidence for this round is built entirely from what the
        # verifier itself self-reports below — no deterministic gatherer
        # runs anymore; durable checks are the coder's TDD job
        # (CODE_PROMPT), not verify's.
        evidence = Evidence()
        # When design classified a boundary (http/ui/both), an explore
        # turn launches and exercises the running project for real
        # before the verdict turn adjudicates (feature 005, US1). A
        # "none"/unclassified boundary skips straight to the verdict
        # turn, unchanged from today.
        explore_resume_id: str | None = None
        if run.boundary in ("http", "ui", "both"):
            explore_prompt = EXPLORE_PROMPT.format(
                boundary=run.boundary, prd=prd, design=design,
                screenshots_dir=screenshots.stage_reldir(run, "verify"),
            )
            service._debug_log(
                run, f"Round {iteration + 1} — EXPLORE PROMPT",
                explore_prompt,
            )
            explore_result = await service._run_turn_tracked(
                run,
                service.backends.backend_for(Step.VERIFY),
                TurnRequest(
                    prompt=explore_prompt,
                    cwd=run.workspace,
                    permission_mode=EXPLORE_PERMISSION_MODE,
                    model=verify_model,
                ),
                verify_slot,
                _bind(verify_step, verify_slot),
            )
            explore_resume_id = explore_result.session_id
            service._debug_log(
                run, f"Round {iteration + 1} — EXPLORE RESULT",
                explore_result.final_text,
            )
        verify_prompt = VERIFY_PROMPT.format(prd=prd, design=design)
        service._debug_log(
            run, f"Round {iteration + 1} — VERIFY PROMPT", verify_prompt
        )
        verify_result = await service._run_turn_tracked(
            run,
            service.backends.backend_for(Step.VERIFY),
            TurnRequest(
                # The verifier gets PRD/design INLINE, not as file
                # pointers. It must emit a strict <VERDICT> JSON block
                # (a parse miss is a hard reject, no fallback), and it
                # runs in plan mode — forcing a tool round-trip to read
                # the files pushes it into an investigate/plan flow that
                # stops reliably emitting the verdict. Its cwd is still
                # the worktree, so a future repo-reading verifier keeps
                # full file access regardless of this. This discipline is
                # exactly why a boundary run's exploration happens on a
                # SEPARATE prior turn (above) rather than in this one.
                prompt=verify_prompt,
                cwd=run.workspace, permission_mode="plan",
                model=verify_model, resume_id=explore_resume_id,
            ),
            verify_slot,
            _bind(verify_step, verify_slot),
        )
        service._debug_log(
            run, f"Round {iteration + 1} — VERIFY RESULT (raw)",
            verify_result.final_text,
        )
        accept, feedback, observations = _parse_verdict(
            verify_result.final_text
        )
        # Self-reported http/ui observations are this round's entire
        # Evidence (feature 005, US1) — merge them in before applying
        # the failing-observation invariant below.
        evidence.observations.extend(observations)
        # Failing-observation invariant: a failing observation never
        # accepts, regardless of what the verdict's own text says.
        if not evidence.all_passed():
            ev_fb = _evidence_feedback(evidence)
            feedback = f"{ev_fb}\n\n{feedback}".strip()
            accept = False
        verify_step.active_sessions = []
        verify_step.deliverable = (
            "accepted" if accept else f"rejected: {feedback}"
        )
        service._debug_log(
            run, f"Round {iteration + 1} — VERDICT",
            f"accept={accept}\nfeedback={feedback or '(none)'}",
        )
        rounds.append({
            "round": len(rounds) + 1, "boundary": run.boundary,
            "accept": accept, "feedback": feedback, "evidence": evidence,
        })
        if accept:
            verify_step.status = "done"
            _flush_report()
            service._save(run)
            return False
        # Rejected: loop back to the coder with the feedback.
        code_step.status = "pending"
        service._save(run)
        prompt = CODE_FEEDBACK_PROMPT.format(
            feedback=feedback,
            design=service._artifact_slot(Step.CODE, run, "design.md", design),
        )
    _flush_report()
    return await escalate(
        service, run, "verification did not pass within the iteration limit"
    )

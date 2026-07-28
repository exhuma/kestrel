"""Per-profile question generation, reconciliation, and coverage critique."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from app.models_workflow import StepSession, WorkflowRun
from app.profiles import get_profile, roster_summary
from app.questionnaire import (
    GenerationIssue,
    ProfileMeta,
    QAEntry,
    Question,
    Questionnaire,
    coerce_answerable,
    render_qa,
)
from app.services.workflow_text import extract_coverage, extract_questionnaire
from app.services.workflows.interview.agent import run_refine_agent
from app.services.workflows.prompts import (
    CRITIC_PROMPT,
    GENERATION_PROMPT,
    MAX_SPECIALIST_RETRIES,
    RECONCILE_PROMPT,
)
from app.services.workflows.sessions import _failure_reason

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService

_logger = logging.getLogger(__name__)


def dedup_questions(questions: list[Question]) -> list[Question]:
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


async def generate_questions(
    service: "WorkflowService",
    run: WorkflowRun,
    issue: str,
    accumulated: list[QAEntry],
    profile_ids: list[str],
    attempts: dict[str, int],
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
        pid: StepSession(profile_id=p.id, label=p.label, badge=p.badge)
        for pid, p in profiles_by_id.items()
    }
    service._show_sessions(run, list(slots.values()))

    samples = max(1, service.settings.refine_samples)

    async def _one(pid: str) -> tuple[str, list[Questionnaire | None]]:
        profile = profiles_by_id[pid]

        async def _sample() -> Questionnaire | None:
            text = await run_refine_agent(
                service,
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
    issues: list[GenerationIssue] = []

    def _fail(pid: str, reason: str) -> None:
        # Count the attempt and classify: a specialist stays "soft"
        # (retried on the next submission) until its retry budget is
        # spent, then becomes a "hard" failure.
        attempts[pid] = attempts.get(pid, 0) + 1
        severity = (
            "hard" if attempts[pid] > MAX_SPECIALIST_RETRIES else "soft"
        )
        slots[pid].status = "error"
        slots[pid].error = reason
        issues.append(GenerationIssue(
            profile=pid, label=slots[pid].label, reason=reason,
            severity=severity,
        ))

    for pid, outcome in zip(ordered, raw, strict=True):
        if isinstance(outcome, Exception):
            reason = _failure_reason(outcome)
            _fail(pid, reason)
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
        _fail(pid, "no response (empty or unparseable output)")
        _logger.warning("refine profile %s produced no questionnaire", pid)
    if issues:
        service._show_sessions(run, list(slots.values()))
    # A round where every specialist failed is no longer fatal: the
    # failures are recorded as (soft) issues and retried on the next
    # answer submission, up to each specialist's retry cap.

    questions: list[Question] = []
    for pid, questionnaires in results:
        profile = profiles_by_id[pid]
        for sample_index, questionnaire in enumerate(questionnaires):
            if questionnaire is None:
                continue
            for q_index, question in enumerate(questionnaire.questions):
                question.audience = profile.id
                # Namespace by profile (and sample, when ensembling)
                # and re-key by position rather than the model's own
                # id: a weak model that reuses an id would otherwise
                # produce colliding ids that break the frontend's
                # per-id answer map and v-for keys.
                tag = f"s{sample_index}:" if samples > 1 else ""
                question.id = f"{profile.id}:{tag}q{q_index}"
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
    mode = service.settings.reconcile_mode
    if mode == "dedup":
        if len(questions) > 1:
            questions = dedup_questions(questions)
    elif mode == "rewrite":
        audiences = {q.audience for q in questions}
        if len(audiences) > 1 and len(questions) > 1:
            questions = await reconcile_questions(
                service, run, issue, questions
            )

    # A weak model can emit a select with no options — unanswerable in
    # the UI (no choices render). Coerce those to free text so every
    # question stays answerable.
    coerce_answerable(questions)

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
        questions=questions, profiles=list(profiles.values()), issues=issues,
    )


async def reconcile_questions(
    service: "WorkflowService",
    run: WorkflowRun,
    issue: str,
    questions: list[Question],
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
    slot = StepSession(profile_id="reconciler", label="Reconciler", badge="sys")
    service._show_sessions(run, [slot])
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
                    {"value": o.value, "label": o.label} for o in q.options
                ],
            }
            for q in questions
        ]
    )
    text = await run_refine_agent(
        service,
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
    if service.settings.refine_critic:
        rebuilt = await critique_coverage(
            service, run, issue, questions, rebuilt
        )
    return rebuilt


async def critique_coverage(
    service: "WorkflowService",
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
    slot = StepSession(profile_id="critic", label="Critic", badge="sys")
    service._show_sessions(run, [slot])
    pool_audiences = {q.audience for q in pool}

    def _payload(items: list[Question]) -> str:
        return json.dumps(
            [
                {"id": q.id, "audience": q.audience,
                 "prompt": q.prompt, "why": q.why}
                for q in items
            ]
        )

    text = await run_refine_agent(
        service,
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

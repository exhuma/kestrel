"""Refinement-interview and PRD-draft parsing and routing (feature 026,
T078).

A `requester`/`pm`/`uiux` ``refinement`` card proposes its own persona-
scoped question set; this module turns it into a ``refinement_gate`` card
holding it for the operator to answer. Once every persona's gate is
answered, `pm`'s ``prd`` card drafts a PRD folding in all three answers;
this module turns that into a ``prd_gate`` card holding it for approval.
An unparseable proposal is routed as an escalation too (fail closed),
the same convention ``decomposition.py``/``verification.py`` use.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.models_board import CardKind, CardState, WorkCard
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.coordinator import CoordinatorService, CreateCardAction
from app.services.board.gates import GatesService
from app.services.board.questions import (
    Question,
    QuestionError,
    normalise_questions,
)
from app.text_extract import extract_tag

#: The one logical name every gate resolution's free-text response is
#: stored under, regardless of gate kind or decision — each gate
#: resolves exactly once, so there is no collision to disambiguate.
RESPONSE_LOGICAL_NAME = "response"


class RefinementResultError(Exception):
    """Raised when a refinement or PRD proposal cannot be trusted."""


@dataclass(frozen=True)
class RefinementRound:
    """One persona interview round's parsed proposal (feature 028).

    :param questions: This round's question set — empty only when
        ``satisfied`` is ``true``.
    :param satisfied: Whether the persona is declaring its interview
        complete, needing no further round.
    """

    questions: list[Question]
    satisfied: bool


def parse_refinement_round(text: str) -> RefinementRound:
    """Parse the ``<REFINEMENT_QUESTIONS>`` block.

    An empty ``questions`` list is only valid alongside
    ``"satisfied": true`` (feature 028) — the persona declaring it has
    no further questions; a missing ``"satisfied"`` key defaults to
    ``false``, so text produced before this field existed parses
    identically to before.

    :raises RefinementResultError: If the tag is absent, the block isn't
        valid JSON of the right shape, or ``questions`` is empty while
        not ``satisfied`` — always fail closed rather than guess.
    """
    raw = extract_tag(text, "REFINEMENT_QUESTIONS")
    if raw is None:
        raise RefinementResultError("no REFINEMENT_QUESTIONS block")
    try:
        data = json.loads(raw)
        questions = normalise_questions(data["questions"])
        satisfied = bool(data.get("satisfied", False))
        if not questions and not satisfied:
            raise RefinementResultError("questions must be a nonempty list")
    except QuestionError as exc:
        raise RefinementResultError(f"malformed question: {exc}") from exc
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RefinementResultError(f"malformed result: {exc}") from exc
    return RefinementRound(questions=questions, satisfied=satisfied)


def parse_refinement_questions(text: str) -> list[Question]:
    """Parse the ``<REFINEMENT_QUESTIONS>`` block's question list.

    Thin wrapper over :func:`parse_refinement_round` for callers (the
    CAB-1 strategic interview) that only need the questions, not the
    feature-028 satisfaction signal.

    :raises RefinementResultError: See :func:`parse_refinement_round`.
    """
    return parse_refinement_round(text).questions


def route_refinement_result(
    text: str,
    card: WorkCard,
    coordinator: CoordinatorService,
    gates: GatesService,
    artifacts: ArtifactsService,
) -> None:
    """Parse *card*'s persona question set and hold it behind a gate.

    *card* is eligible for exactly one persona
    (``requester``/``pm``/``uiux``); that persona names the gate.
    """
    persona = card.eligible_roles[0] if card.eligible_roles else "unknown"
    try:
        round_result = parse_refinement_round(text)
    except RefinementResultError:
        _escalate_unparseable(coordinator, card, "refinement", persona)
        return
    if round_result.satisfied and not round_result.questions:
        gates.mark_refinement_satisfied(card)
        return
    questions = round_result.questions
    artifact = artifacts.store_reference_artifact(
        ArtifactDraft(
            producer_card_id=card.id,
            logical_name="questions",
            revision=card.attempt_count,
            # Normalised, so the interview reads one shape (feature 034).
            content=json.dumps(
                {"questions": questions,
                 "satisfied": round_result.satisfied}
            ),
            trust="agent_output",
        )
    )
    gates.create_gate(
        card.workflow_id,
        kind=CardKind.REFINEMENT_GATE.value,
        title=f"{persona} interview ({len(questions)} question"
        f"{'s' if len(questions) != 1 else ''})",
        requested_decision="answer",
        target_artifact_id=artifact.id,
    )


def route_strategic_interview_result(
    text: str,
    card: WorkCard,
    coordinator: CoordinatorService,
    gates: GatesService,
    artifacts: ArtifactsService,
) -> None:
    """Parse the requester's strategic-fit question set and hold it,
    capped, behind a gate for the requester to answer (feature 027).

    Reuses the ``<REFINEMENT_QUESTIONS>`` tag ``refinement`` cards already
    produce — same shape, lighter intent — and truncates to
    :attr:`GatesService.cab1_interview_max_questions` rather than failing
    closed on an over-long proposal; fail-closed parsing already guards
    the question *content*, not its count.
    """
    try:
        questions = parse_refinement_questions(text)
    except RefinementResultError:
        _escalate_unparseable(
            coordinator, card, "strategic interview", "requester"
        )
        return
    questions = questions[: gates.cab1_interview_max_questions]
    artifact = artifacts.store_reference_artifact(
        ArtifactDraft(
            producer_card_id=card.id,
            logical_name="questions",
            revision=card.attempt_count,
            content=json.dumps({"questions": questions}),
            trust="agent_output",
        )
    )
    gates.create_gate(
        card.workflow_id,
        kind=CardKind.STRATEGIC_INTERVIEW_GATE.value,
        title=f"Strategic fit ({len(questions)} question"
        f"{'s' if len(questions) != 1 else ''})",
        requested_decision="answer",
        target_artifact_id=artifact.id,
    )


def parse_prd_draft(text: str) -> str:
    """Parse the ``<PRD>`` block.

    :raises RefinementResultError: If the tag is absent or empty.
    """
    raw = extract_tag(text, "PRD")
    if raw is None or not raw.strip():
        raise RefinementResultError("no (non-empty) PRD block")
    return raw


def route_prd_result(
    text: str,
    card: WorkCard,
    coordinator: CoordinatorService,
    gates: GatesService,
    artifacts: ArtifactsService,
) -> None:
    """Parse *card*'s PRD draft and hold it behind a gate."""
    try:
        draft = parse_prd_draft(text)
    except RefinementResultError:
        _escalate_unparseable(coordinator, card, "PRD", "pm")
        return
    artifact = artifacts.store_reference_artifact(
        ArtifactDraft(
            producer_card_id=card.id,
            logical_name="draft",
            revision=card.attempt_count,
            content=draft,
            trust="agent_output",
        )
    )
    gates.create_gate(
        card.workflow_id,
        kind=CardKind.PRD_GATE.value,
        title="Approve PRD",
        requested_decision="approve_prd",
        target_artifact_id=artifact.id,
    )


def _escalate_unparseable(
    coordinator: CoordinatorService, card: WorkCard, label: str, persona: str
) -> None:
    trigger = f"{card.kind}:{card.id}:{card.attempt_count}"
    coordinator.apply_actions(
        card.workflow_id, trigger,
        [
            CreateCardAction(
                kind=CardKind.COORDINATOR_REVIEW.value,
                title=f"Unparseable {label} proposal from {persona} "
                f"on card {card.id}",
            )
        ],
    )


def gather_refinement_context(
    workflow_id: str, store: BoardStore, artifacts: ArtifactsService
) -> str:
    """Assemble every answered interview and prior PRD rejection
    feedback for a workflow's ``prd`` card envelope.

    :returns: A formatted block, or ``""`` if nothing has been answered
        yet (a ``prd`` card is never ready before its three interviews
        are, so this should not normally happen).
    """
    sections = []
    for card in store.list_cards(workflow_id):
        if (
            card.kind == CardKind.REFINEMENT_GATE.value
            and card.state == CardState.DONE.value
        ):
            answer = artifacts.latest_content_for_card(
                card.id, RESPONSE_LOGICAL_NAME
            )
            if answer:
                sections.append(f"### {card.title}\n{answer}")
        elif (
            card.kind == CardKind.PRD_GATE.value
            and card.state == CardState.CANCELLED.value
        ):
            feedback = artifacts.latest_content_for_card(
                card.id, RESPONSE_LOGICAL_NAME
            )
            if feedback:
                sections.append(f"### Prior rejection feedback\n{feedback}")
    return "\n\n".join(sections)

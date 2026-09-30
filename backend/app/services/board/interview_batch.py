"""Interview batches and what has been asked so far (feature 038).

The coordinator runs the interview in batches. An ``interview_plan`` card
names the specialists to interview; each gets a ``refinement`` card that
depends on the plan, and that dependency is what makes them one batch.
Every card in a batch drafts its questions, the batch is reviewed for
questions asked twice, its gates open, and once all are answered the
coordinator plans the next batch.

This module reads that state; ``interview_plan.py`` and
``question_review.py`` act on it. A refinement card depending on no plan
belongs to the one batch of an interview that began before feature 038.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.models_board import (
    TERMINAL_STATES,
    CardKind,
    CardRelation,
    CardState,
    WorkCard,
)
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactsService
from app.services.board.questions import Question, prompt_of
from app.services.board.refinement_rounds import GetGate

QUESTIONS = "questions"
RESPONSE = "response"

#: Gates whose answers are interview history.
_ANSWERED_KINDS = frozenset({
    CardKind.REFINEMENT_GATE.value, CardKind.STRATEGIC_INTERVIEW_GATE.value,
})


class Draft(StrEnum):
    """Where one interview card of a batch stands."""

    DRAFTING = "drafting"      # still to write its questions
    TO_REVIEW = "to_review"    # has questions, no gate yet
    ASKING = "asking"          # its gate waits for the human
    SETTLED = "settled"        # answered, done, or nothing to ask


@dataclass(frozen=True)
class InterviewBoard:
    """What the interview modules read the board through."""

    store: BoardStore
    get_gate: GetGate
    artifacts: ArtifactsService


@dataclass(frozen=True)
class Answered:
    """One answered interview: who asked, what, and the human's answer."""

    gate_id: str
    persona: str
    prompts: list[str]
    answer: str


def plans(cards: list[WorkCard]) -> list[WorkCard]:
    """The workflow's interview plans, oldest first."""
    return [c for c in cards if c.kind == CardKind.INTERVIEW_PLAN.value]


def plan_id_of(board: InterviewBoard, card: WorkCard) -> str | None:
    """The plan *card* (a refinement card) belongs to, or ``None``."""
    plan_ids = {c.id for c in plans(board.store.list_cards(card.workflow_id))}
    return next(
        (
            r.depends_on_card_id
            for r in board.store.list_relations(card.workflow_id)
            if r.card_id == card.id and r.depends_on_card_id in plan_ids
        ),
        None,
    )


def batch(
    board: InterviewBoard, workflow_id: str, plan_id: str | None
) -> list[WorkCard]:
    """The refinement cards of *plan_id*'s batch (``None``: the batch of
    an interview begun before feature 038)."""
    cards = board.store.list_cards(workflow_id)
    plan_ids = {c.id for c in plans(cards)}
    planned = {
        r.card_id: r.depends_on_card_id
        for r in board.store.list_relations(workflow_id)
        if r.depends_on_card_id in plan_ids
    }
    return [
        c for c in cards
        if c.kind == CardKind.REFINEMENT.value and planned.get(c.id) == plan_id
    ]


def gates_by_producer(
    board: InterviewBoard, workflow_id: str
) -> dict[str, WorkCard]:
    """Each refinement card's gate, keyed by the refinement card's id."""
    found: dict[str, WorkCard] = {}
    for card in board.store.list_cards(workflow_id):
        if card.kind != CardKind.REFINEMENT_GATE.value:
            continue
        producer = _producer_of(board, card)
        if producer is not None:
            found[producer] = card
    return found


def draft_of(
    board: InterviewBoard, card: WorkCard, gate: WorkCard | None
) -> Draft:
    """Where *card* stands in its batch. A card's accepted result
    completes it, so a done card with questions and no gate yet is
    waiting for its batch's review; a round with nothing to ask (or
    whose questions were all asked elsewhere) is settled."""
    if card.state not in TERMINAL_STATES:
        return Draft.DRAFTING
    if card.state != CardState.DONE.value:
        return Draft.SETTLED  # failed or cancelled: nothing to ask
    if gate is not None:
        settled = gate.state in TERMINAL_STATES
        return Draft.SETTLED if settled else Draft.ASKING
    if questions_of(board, card):
        return Draft.TO_REVIEW
    return Draft.SETTLED


def drafts(
    board: InterviewBoard, workflow_id: str, cards: list[WorkCard]
) -> list[tuple[WorkCard, Draft]]:
    """Every card of a batch with where it stands."""
    gates = gates_by_producer(board, workflow_id)
    return [(c, draft_of(board, c, gates.get(c.id))) for c in cards]


def questions_of(board: InterviewBoard, card: WorkCard) -> list[Question]:
    """*card*'s current question set (after any review), or ``[]``."""
    content = board.artifacts.latest_content_for_card(card.id, QUESTIONS)
    return _questions(content)


def answered_interviews(
    board: InterviewBoard, workflow_id: str
) -> list[Answered]:
    """Every answered interview of the workflow, oldest first — the
    strategic interview included."""
    cards = board.store.list_cards(workflow_id)
    by_id = {c.id: c for c in cards}
    found = []
    for gate in cards:
        if gate.kind not in _ANSWERED_KINDS:
            continue
        if gate.state != CardState.DONE.value:
            continue
        answer = board.artifacts.latest_content_for_card(gate.id, RESPONSE)
        producer = by_id.get(_producer_of(board, gate) or "")
        record = board.get_gate(gate.id)
        target = record.target_artifact_id if record else None
        content = board.artifacts.read_content(target) if target else None
        found.append(Answered(
            gate_id=gate.id,
            persona=_persona(producer),
            prompts=[p for p in map(prompt_of, _questions(content)) if p],
            answer=answer or "",
        ))
    return found


def open_plan(store, workflow_id: str, after: str | None = None) -> WorkCard:
    """Create the next ``interview_plan`` card; *after* is the plan whose
    batch was just answered, which it depends on."""
    number = len(plans(store.list_cards(workflow_id))) + 1
    card = WorkCard(
        id=f"card-{uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        kind=CardKind.INTERVIEW_PLAN.value,
        title=f"Plan interview round {number}",
        state=CardState.READY,
        eligible_roles=("coordinator",),
    )
    store.create_card(card)
    if after is not None:
        store.add_relation(
            CardRelation(card_id=card.id, depends_on_card_id=after),
            created_by_action="interview_plan",
        )
    return card


def maybe_plan_next(card: WorkCard, board: InterviewBoard) -> None:
    """Plan the next batch once every interview in *card*'s batch is
    answered or over. *card* is a refinement card or its gate; a no-op
    for anything else, or while the batch is still under way."""
    refinement = _refinement_card(card, board)
    if refinement is None:
        return
    workflow_id = refinement.workflow_id
    plan_id = plan_id_of(board, refinement)
    cards = board.store.list_cards(workflow_id)
    if _already_planned(board, cards, plan_id):
        return
    members = drafts(board, workflow_id, batch(board, workflow_id, plan_id))
    if all(draft == Draft.SETTLED for _card, draft in members):
        open_plan(board.store, workflow_id, after=plan_id)


def rounds_used(cards: list[WorkCard], persona: str) -> int:
    """How many interview rounds *persona* has had."""
    return sum(
        1 for c in cards
        if c.kind == CardKind.REFINEMENT.value and persona in c.eligible_roles
    )


def _refinement_card(
    card: WorkCard, board: InterviewBoard
) -> WorkCard | None:
    """*card* itself if a refinement card, or its gate's producer."""
    if card.kind == CardKind.REFINEMENT.value:
        return card
    if card.kind != CardKind.REFINEMENT_GATE.value:
        return None
    record = board.get_gate(card.id)
    target = record.target_artifact_id if record else None
    producer = board.artifacts.producer_card_id(target) if target else None
    return board.store.get_card(producer) if producer else None


def _already_planned(
    board: InterviewBoard, cards: list[WorkCard], plan_id: str | None
) -> bool:
    """Whether a plan already follows *plan_id*'s batch."""
    if plan_id is None:  # a pre-038 interview: any plan follows it
        return bool(plans(cards))
    plan_ids = {c.id for c in plans(cards)}
    return any(
        r.depends_on_card_id == plan_id and r.card_id in plan_ids
        for r in board.store.list_relations(cards[0].workflow_id)
    )


def _producer_of(board: InterviewBoard, gate: WorkCard) -> str | None:
    record = board.get_gate(gate.id)
    if record is None or record.target_artifact_id is None:
        return None
    return board.artifacts.producer_card_id(record.target_artifact_id)


def _persona(producer: WorkCard | None) -> str:
    if producer is None or not producer.eligible_roles:
        return "requester"
    return producer.eligible_roles[0]


def _questions(content: str | None) -> list[Question]:
    try:
        questions = json.loads(content or "").get("questions")
    except (ValueError, AttributeError):
        return []
    return questions if isinstance(questions, list) else []

"""No question is asked twice (feature 038).

Once every interview card of a batch has drafted its questions, and
before any human sees them, a ``question_review`` card shows the
coordinator the batch next to everything already asked. It may only drop
a new question as a duplicate of one that is kept, or of one asked
earlier — choosing which profile keeps it — never reword or merge. It
may also give a kept open question its options (feature 045, see
:mod:`question_shaping`).

Code enforces that. A reply it cannot read, or one breaking a rule, is
ignored as a whole and every question set opens unchanged, so no
question is ever lost. A profile whose whole set was dropped has no gate
this round; its next round shows it the answers given on its behalf.
"""
from __future__ import annotations

import json
import uuid

from app.models_board import CardKind, CardRelation, CardState, WorkCard
from app.services.board.artifacts import ArtifactDraft
from app.services.board.interview_answers import answer_to
from app.services.board.interview_batch import (
    QUESTIONS,
    Draft,
    answered_interviews,
    batch,
    drafts,
    maybe_plan_next,
    plan_id_of,
    plans,
    questions_of,
)
from app.services.board.interview_plan import InterviewServices
from app.services.board.question_shaping import (
    CHOICE_INSTRUCTIONS,
    converted,
    parse_choices,
)
from app.services.board.questions import Question, is_open, prompt_of
from app.text_extract import extract_tag

REVIEW_TAG = "QUESTION_REVIEW"
_RECORD = "review"


def after_draft(card: WorkCard, services: InterviewServices) -> None:
    """Once *card*'s whole batch has drafted: review it, or — with one
    question set of choices only and nothing asked before — open its gate
    directly."""
    board = services.board
    plan_id = plan_id_of(board, card)
    members = drafts(
        board, card.workflow_id, batch(board, card.workflow_id, plan_id)
    )
    if any(draft == Draft.DRAFTING for _card, draft in members):
        return
    pending = [c for c, draft in members if draft == Draft.TO_REVIEW]
    if not pending:
        maybe_plan_next(card, board)
        return
    if _review_exists(services, card.workflow_id, plan_id):
        return
    if len(pending) == 1 and not _needs_review(pending[0], services):
        _open_gate(pending[0], services)
        return
    _create_review(card.workflow_id, plan_id, services)


def _needs_review(card: WorkCard, services: InterviewServices) -> bool:
    """A lone set is reviewed when something was asked before, or when an
    open question of it might deserve options (feature 045)."""
    board = services.board
    return bool(answered_interviews(board, card.workflow_id)) or any(
        is_open(q) for q in questions_of(board, card)
    )


def reconcile_interviews(
    workflow_id: str, services: InterviewServices
) -> None:
    """Move every interview batch on as far as it can go (feature 040).

    A batch moves on when a draft is routed or a gate is answered, but a
    card can also leave its batch another way — recovery failing it, the
    operator cancelling it. Run on every dispatch so the batch still
    moves on. Idempotent; a no-op once the PRD exists, so an interview
    that already ended is never reopened.
    """
    cards = services.routing.store.list_cards(workflow_id)
    if any(c.kind in _AFTER_INTERVIEW for c in cards):
        return
    board = services.board
    for plan_id in [None, *(c.id for c in plans(cards))]:
        members = batch(board, workflow_id, plan_id)
        if members:
            after_draft(members[0], services)


#: Once one of these exists, the interview is over.
_AFTER_INTERVIEW = frozenset({CardKind.PRD.value, CardKind.PRD_GATE.value})


def review_context(card: WorkCard, services: InterviewServices) -> str:
    """The envelope for a ``question_review`` card."""
    new, earlier = _catalogue(card, services)
    lines = [_REVIEW_INSTRUCTIONS, "", "Asked before (with the answers):"]
    lines += [
        f"- {qid}: [{persona}] {prompt} — answered: {answer}"
        for qid, (persona, prompt, answer) in earlier.items()
    ] or ["(nothing)"]
    lines += ["", "New questions, by specialist:"]
    lines += [
        f"- {qid} ({'open' if is_open(q) else 'choice'}): {prompt_of(q)}"
        for qid, (_c, q) in new.items()
    ]
    return "\n".join(lines)


def route_review_result(
    text: str, card: WorkCard, services: InterviewServices
) -> None:
    """Apply the review: drop the duplicates it names, give options to
    the open questions it names, open the gates."""
    new, earlier = _catalogue(card, services)
    drops = parse_drops(text, set(new), set(earlier))
    choices = parse_choices(
        text, REVIEW_TAG, {qid: q for qid, (_c, q) in new.items()},
        set(drops or {}),
    )
    if drops is None or choices is None:  # one bad part voids the review
        drops, choices = None, None
    record: _Record = {"drops": [], "choices": []}
    for pending in _pending(card, services):
        persona = pending.eligible_roles[0]
        questions = questions_of(services.board, pending)
        kept = [
            (choices or {}).get(f"{persona}-{index}", q)
            for index, q in enumerate(questions, 1)
            if f"{persona}-{index}" not in (drops or {})
        ]
        if drops is not None:
            record["drops"] += _dropped(persona, questions, drops, new, earlier)
            record["choices"] += converted(persona, questions, choices or {})
        _apply(pending, questions, kept, services)
    _store_record(card, record, services)
    services.routing.gates.transition(
        card.id, CardState.DONE.value,
        event_type="question_review.applied" if drops is not None
        else "question_review.ignored",
    )
    maybe_plan_next(card_of_batch(card, services), services.board)


def parse_drops(
    text: str, new_ids: set[str], earlier_ids: set[str]
) -> dict[str, str] | None:
    """``{dropped id: the id it duplicates}``, or ``None`` when the reply
    is unreadable or breaks a rule (then nothing is dropped)."""
    try:
        entries = json.loads(extract_tag(text, REVIEW_TAG) or "")["drop"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(entries, list):
        return None
    drops: dict[str, str] = {}
    for entry in entries:
        pair = _pair(entry)
        if pair is None or pair[0] in drops:
            return None
        question, original = pair
        known = original in new_ids or original in earlier_ids
        if question not in new_ids or not known or question == original:
            return None
        drops[question] = original
    # A question something duplicates must itself be kept: no chains.
    return None if any(o in drops for o in drops.values()) else drops


def answered_elsewhere(card: WorkCard, services: InterviewServices) -> str:
    """For a refinement card: its persona's questions that were asked of
    another profile instead, with the answers given there (FR-006)."""
    persona = card.eligible_roles[0] if card.eligible_roles else ""
    answered = answered_interviews(services.board, card.workflow_id)
    lines = []
    for entry in _records(card.workflow_id, services):
        if entry.get("persona") != persona:
            continue
        kept_by, kept = entry.get("kept_by"), entry.get("kept_prompt", "")
        answer = next(
            (answer_to(a.answer, kept) for a in answered
             if a.persona == kept_by and kept in a.prompts),
            "",
        ) or "(not answered yet)"
        lines.append(
            f"- {entry.get('prompt')} — asked of {kept_by} as “{kept}”: "
            f"{answer}"
        )
    if not lines:
        return ""
    return "\n".join(
        ["Your questions that another profile answered instead:", *lines]
    )


def card_of_batch(review: WorkCard, services: InterviewServices) -> WorkCard:
    """A refinement card of *review*'s batch (to check it is answered)."""
    plan_id = _plan_of_review(review, services)
    members = batch(services.board, review.workflow_id, plan_id)
    return members[0] if members else review


def _pair(entry: object) -> tuple[str, str] | None:
    if not isinstance(entry, dict):
        return None
    question, original = entry.get("question"), entry.get("duplicate_of")
    if isinstance(question, str) and isinstance(original, str):
        return question, original
    return None


def _apply(
    card: WorkCard, questions: list, kept: list, services: InterviewServices
) -> None:
    """Open *card*'s gate on *kept*; with nothing kept, its round ends —
    the reduced, empty set is what marks it settled."""
    if kept != questions:
        latest = services.routing.artifacts.latest_for_card(card.id, QUESTIONS)
        services.routing.artifacts.store_reference_artifact(ArtifactDraft(
            producer_card_id=card.id, logical_name=QUESTIONS,
            revision=(latest.revision if latest else 0) + 1,
            content=json.dumps({"questions": kept}), trust="agent_output",
            mime_type="application/json",
        ))
    if not kept:
        services.routing.gates.transition(
            card.id, CardState.DONE.value,
            event_type="refinement.deduplicated",
        )
        return
    _open_gate(card, services)


def _open_gate(card: WorkCard, services: InterviewServices) -> None:
    artifact = services.routing.artifacts.latest_for_card(card.id, QUESTIONS)
    count = len(questions_of(services.board, card))
    persona = card.eligible_roles[0] if card.eligible_roles else "unknown"
    services.routing.gates.create_gate(
        card.workflow_id,
        kind=CardKind.REFINEMENT_GATE.value,
        title=f"{persona} interview ({count} question"
        f"{'s' if count != 1 else ''})",
        requested_decision="answer",
        target_artifact_id=artifact.id if artifact else None,
    )


def _create_review(
    workflow_id: str, plan_id: str | None, services: InterviewServices
) -> None:
    card = WorkCard(
        id=f"card-{uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        kind=CardKind.QUESTION_REVIEW.value,
        title="Review the questions",
        state=CardState.READY,
        eligible_roles=("coordinator",),
    )
    services.routing.store.create_card(card)
    if plan_id is not None:
        services.routing.store.add_relation(
            CardRelation(card_id=card.id, depends_on_card_id=plan_id),
            created_by_action="question_review",
        )


def _review_exists(
    services: InterviewServices, workflow_id: str, plan_id: str | None
) -> bool:
    return any(
        c.kind == CardKind.QUESTION_REVIEW.value
        and _plan_of_review(c, services) == plan_id
        for c in services.routing.store.list_cards(workflow_id)
    )


def _plan_of_review(
    review: WorkCard, services: InterviewServices
) -> str | None:
    cards = services.routing.store.list_cards(review.workflow_id)
    plan_ids = {c.id for c in cards if c.kind == CardKind.INTERVIEW_PLAN.value}
    return next(
        (
            r.depends_on_card_id
            for r in services.routing.store.list_relations(review.workflow_id)
            if r.card_id == review.id and r.depends_on_card_id in plan_ids
        ),
        None,
    )


def _pending(review: WorkCard, services: InterviewServices) -> list[WorkCard]:
    """The batch's cards whose questions wait for this review."""
    plan_id = _plan_of_review(review, services)
    members = drafts(
        services.board, review.workflow_id,
        batch(services.board, review.workflow_id, plan_id),
    )
    return [c for c, draft in members if draft == Draft.TO_REVIEW]


#: ``earlier-3`` -> (persona, prompt, answer).
_Earlier = dict[str, tuple[str, str, str]]
#: ``uiux-2`` -> (its card, the question as drafted).
_New = dict[str, tuple[WorkCard, Question]]
#: What a review did: the drops, and the questions it made choices.
_Record = dict[str, list[dict[str, object]]]


def _catalogue(
    review: WorkCard, services: InterviewServices
) -> tuple[_New, _Earlier]:
    """Ids for the batch's new questions (``uiux-2``) and for everything
    asked before (``earlier-3``, with its answer)."""
    new: _New = {}
    for card in _pending(review, services):
        persona = card.eligible_roles[0]
        for index, question in enumerate(questions_of(services.board, card), 1):
            new[f"{persona}-{index}"] = (card, question)
    earlier: _Earlier = {}
    for answered in answered_interviews(services.board, review.workflow_id):
        for prompt in answered.prompts:
            answer = answer_to(answered.answer, prompt) or "(no answer)"
            earlier[f"earlier-{len(earlier) + 1}"] = (
                answered.persona, prompt, answer,
            )
    return new, earlier


def _dropped(
    persona: str, questions: list, drops: dict[str, str],
    new: _New, earlier: _Earlier,
) -> list[dict[str, object]]:
    """What was dropped from *persona*'s set, and who keeps it."""
    entries = []
    for index, question in enumerate(questions, 1):
        original = drops.get(f"{persona}-{index}")
        if original is None:
            continue
        if original in new:
            owner, question_kept = new[original]
            kept_by = owner.eligible_roles[0]
            kept = prompt_of(question_kept) or ""
        else:
            kept_by, kept, _answer = earlier[original]
        entries.append({
            "persona": persona, "prompt": prompt_of(question) or "",
            "kept_by": kept_by, "kept_prompt": kept,
        })
    return entries


def _store_record(
    review: WorkCard, record: _Record, services: InterviewServices,
) -> None:
    services.routing.artifacts.store_reference_artifact(ArtifactDraft(
        producer_card_id=review.id, logical_name=_RECORD, revision=1,
        content=json.dumps(record), trust="agent_output",
        mime_type="application/json",
    ))


def _records(
    workflow_id: str, services: InterviewServices
) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for card in services.routing.store.list_cards(workflow_id):
        if card.kind != CardKind.QUESTION_REVIEW.value:
            continue
        content = services.routing.artifacts.latest_content_for_card(
            card.id, _RECORD
        )
        try:
            found += json.loads(content or "").get("drops", [])
        except (ValueError, AttributeError):
            continue
    return [e for e in found if isinstance(e, dict)]


_REVIEW_INSTRUCTIONS = """\
Every specialist in this round has drafted its questions for its own
human. Before anyone sees them, remove the questions asked twice: a new
question that asks the same thing as another new question, or as one
asked before. Keep each duplicated question with the profile whose human
is best placed to answer it, and drop the others. Never reword, merge,
or add a question; anything you do not drop is asked as written.
""" + CHOICE_INSTRUCTIONS + """
Respond with a single block (empty lists when there is nothing to drop
or to give options to):
<QUESTION_REVIEW>{"drop": [
  {"question": "<id to drop>", "duplicate_of": "<id it repeats>"}
], "options": [
  {"question": "<open id>", "options": ["...", "..."], "multiple": false}
]}</QUESTION_REVIEW>"""

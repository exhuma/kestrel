"""The coordinator decides who is interviewed (feature 038).

After CAB-1, and again whenever a batch of interviews is answered, an
``interview_plan`` card asks the coordinator which specialists' humans
must be asked something now. It knows every specialist that can
interview (its manifest allows ``refinement``), their purpose, and the
rounds each has used; answers can bring new specialists in. Naming
nobody completes the interview and starts the PRD — except on the first
plan, which must name someone (fail closed).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from app.models_board import CardKind, CardRelation, CardState, WorkCard
from app.services.board.decomposition import RoutingServices, escalate
from app.services.board.interview_batch import (
    InterviewBoard,
    answered_interviews,
    rounds_used,
)
from app.services.board.specialists import SpecialistRoster
from app.text_extract import extract_tag

PLAN_TAG = "INTERVIEWERS"


class PlanError(ValueError):
    """Raised for an interview plan that cannot be read."""


@dataclass(frozen=True)
class InterviewServices:
    """What the interview routes need, bundled for the argument limit."""

    routing: RoutingServices
    roster: SpecialistRoster

    @property
    def board(self) -> InterviewBoard:
        return InterviewBoard(
            self.routing.store, self.routing.gates.get_gate,
            self.routing.artifacts,
        )


def interviewers(roster: SpecialistRoster) -> list[str]:
    """Every specialist that can interview, by id, in a stable order."""
    return sorted(
        sid for sid in roster.ids()
        if (spec := roster.get(sid)) is not None
        and CardKind.REFINEMENT.value in spec.allowed_card_types
    )


def plan_context(card: WorkCard, services: InterviewServices) -> str:
    """The envelope for an ``interview_plan`` card."""
    board = services.board
    cards = board.store.list_cards(card.workflow_id)
    cap = services.routing.gates.refinement_round_cap
    first = not any(c.kind == CardKind.REFINEMENT.value for c in cards)
    lines = [
        "You are planning who is interviewed next about this request.",
        "", "Specialists who can interview (id — label: purpose — rounds):",
    ]
    for sid in interviewers(services.roster):
        spec = services.roster.get(sid)
        used = rounds_used(cards, sid)
        lines.append(
            f"- {sid} — {spec.label}: {spec.purpose} — {used} of {cap}"
            + (" (no rounds left)" if used >= cap else "")
        )
    lines += ["", "The interview so far:", _history(board, card.workflow_id)]
    lines += ["", _PLAN_INSTRUCTIONS]
    if first:
        lines.append("This is the first round: name at least one specialist.")
    return "\n".join(lines)


def route_plan_result(
    text: str, card: WorkCard, services: InterviewServices
) -> None:
    """Apply the coordinator's plan: a batch of interviews, or the end of
    the interview."""
    routing = services.routing
    cards = routing.store.list_cards(card.workflow_id)
    first = not any(c.kind == CardKind.REFINEMENT.value for c in cards)
    try:
        named = parse_plan(text)
    except PlanError:
        escalate(routing.coordinator, card, "interview_plan",
                 "Unreadable interview plan")
        return
    chosen = _valid(named, services, cards)
    if chosen:
        _start_batch(card, chosen, routing)
    elif first:
        escalate(routing.coordinator, card, "interview_plan",
                 "Interview plan named no interviewer")
        return
    else:
        start_prd(routing, card.workflow_id)
    routing.gates.transition(
        card.id, CardState.DONE.value, event_type="interview.planned"
    )


def parse_plan(text: str) -> list[str]:
    """The specialist ids an ``<INTERVIEWERS>`` block names, in order.

    :raises PlanError: If the block is missing or malformed.
    """
    raw = extract_tag(text, PLAN_TAG)
    try:
        entries = json.loads(raw or "")["interviewers"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PlanError("no readable interviewers list") from exc
    if not isinstance(entries, list):
        raise PlanError("interviewers must be a list")
    return [
        entry["specialist"] for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("specialist"), str)
    ]


def start_prd(routing: RoutingServices, workflow_id: str) -> None:
    """Hand the answered interview to `pm` to draft the PRD, once."""
    cards = routing.store.list_cards(workflow_id)
    if any(
        c.kind in (CardKind.PRD.value, CardKind.PRD_GATE.value) for c in cards
    ):
        return
    routing.store.create_card(WorkCard(
        id=f"card-{uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        kind=CardKind.PRD.value,
        title="Draft PRD",
        state=CardState.READY,
        eligible_roles=("pm",),
    ))


def _valid(
    named: list[str], services: InterviewServices, cards: list[WorkCard]
) -> list[str]:
    """*named*, keeping only interviewers with rounds left, once each."""
    allowed = set(interviewers(services.roster))
    cap = services.routing.gates.refinement_round_cap
    chosen: list[str] = []
    for sid in named:
        has_rounds = rounds_used(cards, sid) < cap
        if sid in allowed and sid not in chosen and has_rounds:
            chosen.append(sid)
    return chosen


def _start_batch(
    plan: WorkCard, chosen: list[str], routing: RoutingServices
) -> None:
    cards = routing.store.list_cards(plan.workflow_id)
    for sid in chosen:
        number = rounds_used(cards, sid) + 1
        card = WorkCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            workflow_id=plan.workflow_id,
            kind=CardKind.REFINEMENT.value,
            title=f"{sid} interview questions (round {number})",
            state=CardState.READY,
            eligible_roles=(sid,),
        )
        routing.store.create_card(card)
        routing.store.add_relation(
            CardRelation(card_id=card.id, depends_on_card_id=plan.id),
            created_by_action="interview_plan",
        )


def _history(board: InterviewBoard, workflow_id: str) -> str:
    answered = answered_interviews(board, workflow_id)
    if not answered:
        return "(nothing asked yet)"
    return "\n\n".join(
        f"### {a.persona}\n{a.answer or '(no answer text)'}" for a in answered
    )


_PLAN_INSTRUCTIONS = """\
Name the specialists whose human must be asked something now. Bring a
specialist in when the request or an answer touches its area — for
example, data being stored brings in the dba, and personal or sensitive
data brings in infosec. Leave out anyone with nothing to ask, and anyone
with no rounds left. Name nobody when nothing more is needed: the PRD is
then drafted from the answers so far. Respond with a single block:
<INTERVIEWERS>{"interviewers": [
  {"specialist": "<id>", "reason": "<why>"}
]}</INTERVIEWERS>"""

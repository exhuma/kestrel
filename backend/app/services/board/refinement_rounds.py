"""Multi-round refinement-interview bookkeeping (feature 028).

Split out of ``gates.py`` purely to stay within the repo's 500-line
module cap — this is not a distinct domain concern, it is
``GatesService.resolve()``'s own approved-branch/completion-check
behavior, just as tightly coupled to gate resolution as the methods
that stayed there.

A persona's round number is *derived* from existing cards (counted, not
stored) — see ``specs/028-refinement-rounds-cap/research.md``'s "round
number is derived, not stored" decision. A ``refinement_gate`` card
itself carries no ``eligible_roles`` (gates are never claimed by a
specialist), so its persona is recovered via its target artifact's
origin ``refinement`` card instead — ``get_gate`` is a
``GatesService.get_gate``-shaped lookup, passed in rather than a whole
``GatesService`` to avoid a circular import (``gates.py`` calls into
this module).
"""
from __future__ import annotations

import uuid
from typing import Callable

from app.models_board import TERMINAL_STATES, CardKind, CardState, WorkCard
from app.models_board_records import HumanGateRecord
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactsService

GetGate = Callable[[str], HumanGateRecord | None]

#: Mirrors ``gates.py``'s own ``_RESPONSE_LOGICAL_NAME`` /
#: ``refinement.py``'s ``RESPONSE_LOGICAL_NAME`` — kept duplicated
#: rather than imported, same reasoning as those modules' own copies:
#: not worth a coupling for one string.
_RESPONSE_LOGICAL_NAME = "response"

def has_any_round(cards: list[WorkCard]) -> bool:
    """Whether refinement has started at all for this workflow — the
    entry guard before checking :func:`still_pending` (mirrors the
    original T078 check: never start PRD drafting for a workflow with
    no interview activity whatsoever)."""
    return any(
        c.kind in (CardKind.REFINEMENT.value, CardKind.REFINEMENT_GATE.value)
        for c in cards
    )


def still_pending(
    cards: list[WorkCard], get_gate: GetGate, artifacts: ArtifactsService
) -> bool:
    """Whether any persona's interview has not yet reached a terminal
    outcome, possibly across several rounds.

    A round is resolved once *either* its ``refinement_gate`` reaches a
    terminal state (the operator answered/rejected it) *or*, if no gate
    was ever created for it, its own ``refinement`` card does (the
    satisfied-with-no-questions path). A ``refinement`` card is *not*
    required to reach a terminal state once a gate already holds its
    output — ``route_refinement_result`` deliberately leaves it in
    ``review`` forever in that case, same as any other specialist card
    whose result a gate now represents — so only a ``refinement`` card
    with no corresponding gate at all counts as still in flight.
    """
    refinement_cards = [
        c for c in cards if c.kind == CardKind.REFINEMENT.value
    ]
    gate_cards = [
        c for c in cards if c.kind == CardKind.REFINEMENT_GATE.value
    ]
    gated_producer_ids = {
        producer_id for g in gate_cards
        if (producer_id := _producer_id_for_gate(g, get_gate, artifacts))
        is not None
    }
    ungated = [c for c in refinement_cards if c.id not in gated_producer_ids]
    if any(CardState(c.state) not in TERMINAL_STATES for c in ungated):
        return True
    return any(CardState(g.state) not in TERMINAL_STATES for g in gate_cards)


def maybe_advance_round(
    resolved_gate: WorkCard,
    store: BoardStore,
    get_gate: GetGate,
    artifacts: ArtifactsService,
    round_cap: int,
) -> None:
    """Create the next interview round for one persona once their
    ``refinement_gate`` is answered, unless they're at the round cap.

    A no-op for any other gate kind, or if the gate's persona can't be
    recovered (should not happen — every ``refinement_gate`` is created
    from a ``refinement`` card's own output artifact).
    """
    if resolved_gate.kind != CardKind.REFINEMENT_GATE.value:
        return
    cards = store.list_cards(resolved_gate.workflow_id)
    persona = _persona_for_gate(resolved_gate, cards, get_gate, artifacts)
    if persona is None:
        return
    round_count = sum(
        1 for c in cards
        if c.kind == CardKind.REFINEMENT.value and persona in c.eligible_roles
    )
    if round_count >= round_cap:
        return
    store.create_card(
        WorkCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            workflow_id=resolved_gate.workflow_id,
            kind=CardKind.REFINEMENT.value,
            title=f"{persona} interview questions (round {round_count + 1})",
            state=CardState.READY,
            eligible_roles=(persona,),
        )
    )


def round_context(
    card: WorkCard,
    cards: list[WorkCard],
    get_gate: GetGate,
    artifacts: ArtifactsService,
    round_cap: int,
) -> str:
    """Build round-N-of-M text for one persona's ``refinement`` card's
    envelope: the round number, the cap, this persona's own prior
    round(s) Q&A, and — on the final round — that no further round
    follows. The final round still asks: a human interview never swaps
    a question for an assumption (feature 037).
    """
    persona = card.eligible_roles[0] if card.eligible_roles else ""
    round_number = sum(
        1 for c in cards
        if c.kind == CardKind.REFINEMENT.value and persona in c.eligible_roles
    )
    lines = [
        f"This is interview round {round_number} of {round_cap} for you."
    ]
    prior = _prior_round_answers(persona, cards, get_gate, artifacts)
    if prior:
        lines += ["", "Your prior round's questions and answers:", prior]
    if round_number >= round_cap:
        lines += [
            "",
            "This is your final round: there is no further round after "
            "it, so ask now everything you still need to know. Never "
            "replace a question with an assumption — ask it.",
        ]
    return "\n".join(lines)


def round_of_gate(
    gate: WorkCard, cards: list[WorkCard], get_gate: GetGate,
    artifacts: ArtifactsService,
) -> int | None:
    """The 1-based round number *gate* belongs to (board API A3/FR-042),
    or ``None`` if *gate* is not a ``refinement_gate`` or its persona
    cannot be recovered (see :func:`_persona_for_gate`).

    Counts the persona's own ``refinement`` cards the same way
    :func:`maybe_advance_round` does, so the two can never disagree.
    """
    if gate.kind != CardKind.REFINEMENT_GATE.value:
        return None
    persona = _persona_for_gate(gate, cards, get_gate, artifacts)
    if persona is None:
        return None
    return sum(
        1 for c in cards
        if c.kind == CardKind.REFINEMENT.value and persona in c.eligible_roles
    )


def _producer_id_for_gate(
    gate: WorkCard, get_gate: GetGate, artifacts: ArtifactsService
) -> str | None:
    """The ``refinement`` card id whose output *gate* holds, or ``None``
    if *gate* has no target artifact (e.g. a test double, or any other
    gate kind)."""
    record = get_gate(gate.id)
    if record is None or record.target_artifact_id is None:
        return None
    return artifacts.producer_card_id(record.target_artifact_id)


def _persona_for_gate(
    gate: WorkCard, cards: list[WorkCard], get_gate: GetGate,
    artifacts: ArtifactsService,
) -> str | None:
    """Recover a ``refinement_gate``'s persona via its target artifact's
    origin ``refinement`` card."""
    producer_id = _producer_id_for_gate(gate, get_gate, artifacts)
    origin = next((c for c in cards if c.id == producer_id), None)
    if origin is None or not origin.eligible_roles:
        return None
    return origin.eligible_roles[0]


def _prior_round_answers(
    persona: str, cards: list[WorkCard], get_gate: GetGate,
    artifacts: ArtifactsService,
) -> str:
    sections = []
    for c in cards:
        if c.kind != CardKind.REFINEMENT_GATE.value:
            continue
        if c.state != CardState.DONE.value:
            continue
        if _persona_for_gate(c, cards, get_gate, artifacts) != persona:
            continue
        answer = artifacts.latest_content_for_card(c.id, _RESPONSE_LOGICAL_NAME)
        if answer:
            sections.append(f"### {c.title}\n{answer}")
    return "\n\n".join(sections)

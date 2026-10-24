"""Interview rounds: a persona's round context, and which persona an
interview gate belongs to (feature 028). Which personas are asked, and
when the next round starts, is the coordinator's plan
(``interview_plan.py``, ``interview_batch.py``; feature 038).

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

from typing import Callable

from app.models_board import CardKind, CardState, WorkCard
from app.models_board_records import HumanGateRecord
from app.services.board.artifacts import ArtifactsService
from app.services.board.retries import live_attempts

GetGate = Callable[[str], HumanGateRecord | None]

#: Mirrors ``gates.py``'s own ``_RESPONSE_LOGICAL_NAME`` /
#: ``refinement.py``'s ``RESPONSE_LOGICAL_NAME`` — kept duplicated
#: rather than imported, same reasoning as those modules' own copies:
#: not worth a coupling for one string.
_RESPONSE_LOGICAL_NAME = "response"


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
        1 for c in live_attempts(cards)
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
    cannot be recovered (see :func:`persona_for_gate`).

    Counts the persona's own ``refinement`` cards the same way
    :func:`maybe_advance_round` does, so the two can never disagree.
    """
    if gate.kind != CardKind.REFINEMENT_GATE.value:
        return None
    persona = persona_for_gate(gate, cards, get_gate, artifacts)
    if persona is None:
        return None
    return sum(
        1 for c in live_attempts(cards)
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


def persona_for_gate(
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
        if persona_for_gate(c, cards, get_gate, artifacts) != persona:
            continue
        answer = artifacts.latest_content_for_card(c.id, _RESPONSE_LOGICAL_NAME)
        if answer:
            sections.append(f"### {c.title}\n{answer}")
    return "\n\n".join(sections)

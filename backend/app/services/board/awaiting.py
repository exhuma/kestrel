"""Who is expected to act on a card, and what they are asked (feature 035).

kestrel has one user, who wears several hats: requester, change advisory
board (CAB), the one doing manual tasks, and operator. "Your move" alone
does not say which hat a decision needs, so two decisions in a row look
the same. This names the hat and the ask as stable codes; the frontend
phrases them (constitution Principle II).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models_board import CardKind, CardState, WorkCard

#: Waiting on a human, by card kind: (actor, ask). The asks for gates are
#: the gates' own ``requested_decision`` literals.
_BY_KIND: dict[str, tuple[str, str]] = {
    CardKind.UNDERSTANDING_GATE.value: ("requester", "confirm_understanding"),
    CardKind.STRATEGIC_INTERVIEW_GATE.value: ("requester", "answer"),
    CardKind.CAB1_GATE.value: ("cab", "approve_strategic_fit"),
    CardKind.REFINEMENT_GATE.value: ("requester", "answer"),
    CardKind.PRD_GATE.value: ("requester", "approve_prd"),
    CardKind.DECOMPOSITION_GATE.value: ("cab", "approve_decomposition"),
    CardKind.MANUAL_TASK.value: ("you", "do_task"),
}

#: Interview gates: a named profile's human answers them (feature 038).
_INTERVIEWS = frozenset({
    CardKind.REFINEMENT_GATE.value, CardKind.STRATEGIC_INTERVIEW_GATE.value,
})

#: Waiting on the operator whatever the card's kind, by state.
_BY_STATE: dict[str, tuple[str, str]] = {
    CardState.QUARANTINED.value: ("operator", "review_input"),
    CardState.FAILED.value: ("operator", "retry_or_cancel"),
}


@dataclass(frozen=True)
class Awaiting:
    """Who a card waits on, and for what.

    :param actor: ``requester``, ``cab``, ``you`` or ``operator`` — or
        ``role``: the human holding *role* (feature 038).
    :param ask: What they are asked, as a code.
    :param role: For ``role``: the specialist id whose human is asked.
    """

    actor: str
    ask: str
    role: str | None = None


def awaiting_of(card: WorkCard, persona: str | None = None) -> Awaiting | None:
    """Who *card* waits on, or ``None`` when it waits on nobody (it is
    working, queued, waiting on other cards, or over). *persona* is the
    profile an interview gate asks (feature 038): its human answers."""
    if card.state in _BY_STATE:
        return Awaiting(*_BY_STATE[card.state])
    if card.state != CardState.AWAITING_HUMAN.value:
        return None
    if persona is not None and card.kind in _INTERVIEWS:
        return Awaiting("role", "answer", persona)
    # Any other card held for a human (a coordinator review, say) is the
    # operator's to look at, so no "your move" is ever left unnamed.
    return Awaiting(*_BY_KIND.get(card.kind, ("operator", "review")))


def awaiting_all(
    cards: list[WorkCard], personas: dict[str, str] | None = None
) -> list[Awaiting]:
    """Every card's :func:`awaiting_of`, in card order, skipping cards
    that wait on nobody. *personas* maps interview gates to their
    profile."""
    found = (awaiting_of(c, (personas or {}).get(c.id)) for c in cards)
    return [a for a in found if a is not None]

"""What the ticket says when a gate is decided (feature 046, review fix).

One mapping, so the wording of every outcome is read and changed in one
place. A decision gate reads as one plain sentence per kind and outcome.
An *answer* gate (an interview) is never announced: people give answers on
a form, and the next announcement (the CAB comment, the next round, the
PRD) is the acknowledgement; a line saying the gate was "approved" would
read as if the thing the interview was about had been.
"""
from __future__ import annotations

from app.models_board import CardKind

#: Gates resolved by submitting answers, not by a decision.
ANSWER_GATES = frozenset({
    CardKind.STRATEGIC_INTERVIEW_GATE.value,
    CardKind.REFINEMENT_GATE.value,
})

_SENTENCES = {
    (CardKind.UNDERSTANDING_GATE.value, True): "Understanding confirmed.",
    (CardKind.UNDERSTANDING_GATE.value, False): (
        "Understanding corrected, kestrel is rewriting it."
    ),
    (CardKind.CAB1_GATE.value, True): "CAB approved the strategic fit.",
    (CardKind.CAB1_GATE.value, False): (
        "CAB declined the strategic fit; this request stops here."
    ),
    (CardKind.PRD_GATE.value, True): "PRD signed off.",
    (CardKind.PRD_GATE.value, False): (
        "PRD sent back with feedback, kestrel is revising it."
    ),
    (CardKind.DECOMPOSITION_GATE.value, True): (
        "CAB approved the plan; work starts."
    ),
    (CardKind.DECOMPOSITION_GATE.value, False): "CAB declined the plan.",
}


def announces_decision(kind: str) -> bool:
    """Whether deciding a *kind* gate is said on the ticket at all."""
    return kind not in ANSWER_GATES


def decision_sentence(kind: str, approved: bool, title: str) -> str:
    """The sentence for a *kind* gate decided, with a neutral line (naming
    the gate's *title*) for a kind without its own wording."""
    found = _SENTENCES.get((kind, approved))
    if found is not None:
        return found
    return f"Gate {'approved' if approved else 'rejected'}: {title}"

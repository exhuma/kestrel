"""Derived phase/stage projection over card kinds (GitHub #55).

A pure, display-only label over existing ``CardKind`` values — ten
phases grouped into six stages. This is **not a driver**: spec 026
FR-037 retired the fixed six-step driver as the operating model, and
this projection must never regain that role. It has no new state
column, writes nothing, and has no bearing on card creation, claiming,
or transitions — it only reads.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models_board import TERMINAL_STATES, CardKind, WorkCard

#: Returned once every card is terminal (or the board is empty) — no
#: phase is outstanding any more.
DONE_PHASE = "done"


@dataclass(frozen=True)
class _PhaseDef:
    name: str
    stage: str
    kinds: frozenset[CardKind]


_PHASES: tuple[_PhaseDef, ...] = (
    _PhaseDef(
        "Intake", "Intake & alignment", frozenset({CardKind.SECURITY_REVIEW})
    ),
    _PhaseDef(
        "Understanding",
        "Intake & alignment",
        frozenset({CardKind.UNDERSTANDING, CardKind.UNDERSTANDING_GATE}),
    ),
    _PhaseDef(
        "CAB-1 - strategic fit",
        "Discovery",
        frozenset(
            {
                CardKind.STRATEGIC_INTERVIEW,
                CardKind.STRATEGIC_INTERVIEW_GATE,
                CardKind.CAB1_GATE,
            }
        ),
    ),
    _PhaseDef(
        "Pre-assessment",
        "Discovery",
        frozenset({
            CardKind.REFINEMENT, CardKind.REFINEMENT_GATE,
            CardKind.INTERVIEW_PLAN, CardKind.QUESTION_REVIEW,
        }),
    ),
    _PhaseDef("PRD", "Definition", frozenset({CardKind.PRD})),
    _PhaseDef("PRD sign-off", "Definition", frozenset({CardKind.PRD_GATE})),
    _PhaseDef(
        "Technical analysis",
        "Planning",
        frozenset(
            {
                CardKind.ANALYSIS,
                CardKind.DESIGN,
                CardKind.DECOMPOSITION,
                CardKind.ESTIMATION,
            }
        ),
    ),
    _PhaseDef(
        "CAB-2 - go/no-go",
        "Planning",
        frozenset({CardKind.DECOMPOSITION_GATE}),
    ),
    _PhaseDef(
        "Build",
        "Build & deliver",
        frozenset(
            {
                CardKind.IMPLEMENTATION,
                CardKind.VERIFICATION,
                CardKind.RECONCILIATION,
                CardKind.COORDINATOR_REVIEW,
                CardKind.MANUAL_TASK,
            }
        ),
    ),
    _PhaseDef("Delivery", "Build & deliver", frozenset({CardKind.DELIVERY})),
)

_PHASE_BY_KIND: dict[CardKind, str] = {
    kind: phase.name for phase in _PHASES for kind in phase.kinds
}
_STAGE_BY_PHASE: dict[str, str] = {
    phase.name: phase.stage for phase in _PHASES
} | {DONE_PHASE: "Done"}


def current_phase(cards: list[WorkCard]) -> str:
    """The lowest-ordinal phase that still has a non-terminal card.

    ``"done"`` once every card is terminal — an empty board included, no
    phase is outstanding. A card whose kind maps to no known phase (e.g.
    a kind added after this projection) is simply not counted, rather
    than raising.
    """
    outstanding = {
        _PHASE_BY_KIND[card.kind]
        for card in cards
        if card.state not in TERMINAL_STATES and card.kind in _PHASE_BY_KIND
    }
    for phase in _PHASES:
        if phase.name in outstanding:
            return phase.name
    return DONE_PHASE


def stage_of(phase: str) -> str:
    """The stage grouping *phase* belongs to."""
    return _STAGE_BY_PHASE.get(phase, phase)


#: Card states that mean a phase waits on the operator, not on work.
_WAITING_STATES = frozenset({"awaiting_human", "quarantined"})


def phase_statuses(cards: list[WorkCard]) -> list[tuple[str, str]]:
    """Every phase, in order, with its status (feature 034): ``done``,
    ``active``, ``waiting``, ``problem``, ``skipped`` or ``upcoming``.

    Still display-only. A phase with no cards is ``skipped`` once the
    request has moved past it (or finished), and ``upcoming`` otherwise.
    """
    by_phase: dict[str, list[WorkCard]] = {p.name: [] for p in _PHASES}
    for card in cards:
        if card.kind in _PHASE_BY_KIND:
            by_phase[_PHASE_BY_KIND[card.kind]].append(card)
    names = [p.name for p in _PHASES]
    finished = current_phase(cards) == DONE_PHASE and bool(cards)
    reached = [i for i, name in enumerate(names) if by_phase[name]]
    last_reached = max(reached, default=-1)
    return [
        (name, _status(by_phase[name], finished or i < last_reached))
        for i, name in enumerate(names)
    ]


def _status(cards: list[WorkCard], passed: bool) -> str:
    if not cards:
        return "skipped" if passed else "upcoming"
    open_states = {c.state for c in cards if c.state not in TERMINAL_STATES}
    if open_states & _WAITING_STATES:
        return "waiting"
    if open_states:
        return "active"
    if any(c.state == "failed" for c in cards):
        return "problem"
    return "done" if any(c.state == "done" for c in cards) else "skipped"

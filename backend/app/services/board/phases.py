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

from app.models_board import TERMINAL_STATES, CardKind, CardState, WorkCard

#: The phase of a request that reached its end (see :func:`outcome_of`).
DONE_PHASE = "done"
#: The phase of a request that stopped before its end, with nothing
#: failed (feature 040): finished, but not done.
CANCELLED_PHASE = "cancelled"

IN_PROGRESS = "in_progress"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"


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
} | {DONE_PHASE: "Done", CANCELLED_PHASE: "Cancelled"}


def outcome_of(cards: list[WorkCard]) -> str:
    """How the request stands overall (feature 040).

    * ``failed`` — any card failed, whatever else is open: it needs the
      operator, and it can never read as done;
    * ``in_progress`` — anything is still open (an empty board too);
    * ``done`` — nothing open or failed, and the request reached its
      end: a done delivery, or — when CAB-2 approved no coding work —
      CAB-2 approval with every approved task done;
    * ``cancelled`` — nothing open or failed, but it stopped before its
      end (a gate rejected, work cancelled). Terminal is not done.
    """
    if any(c.state == CardState.FAILED.value for c in cards):
        return FAILED
    if not cards or any(c.state not in TERMINAL_STATES for c in cards):
        return IN_PROGRESS
    return DONE if _reached_end(cards) else CANCELLED


def _reached_end(cards: list[WorkCard]) -> bool:
    def done(kind: CardKind) -> bool:
        return any(
            c.kind == kind.value and c.state == CardState.DONE.value
            for c in cards
        )

    if done(CardKind.DELIVERY):
        return True
    coding = any(c.kind == CardKind.IMPLEMENTATION.value for c in cards)
    if coding or not done(CardKind.DECOMPOSITION_GATE):
        return False
    tasks = [c for c in cards if c.task_node_id]
    return all(c.state == CardState.DONE.value for c in tasks)


def current_phase(cards: list[WorkCard]) -> str:
    """The lowest-ordinal phase with open work or a failed card.

    ``"done"`` only for a request that reached its end, ``"cancelled"``
    for one that stopped before it (:func:`outcome_of`). A failed
    request stays at the phase of its failure. A card whose kind maps to
    no known phase (e.g. a kind added after this projection) is not
    counted, rather than raising; open work of that kind leaves the
    request at the furthest phase it reached.
    """
    outcome = outcome_of(cards)
    if outcome == DONE:
        return DONE_PHASE
    if outcome == CANCELLED:
        return CANCELLED_PHASE
    outstanding = {
        _PHASE_BY_KIND[card.kind]
        for card in cards
        if card.kind in _PHASE_BY_KIND and _outstanding(card)
    }
    for phase in _PHASES:
        if phase.name in outstanding:
            return phase.name
    return _furthest_reached(cards)


def _outstanding(card: WorkCard) -> bool:
    open_ = card.state not in TERMINAL_STATES
    return open_ or card.state == CardState.FAILED.value


def _furthest_reached(cards: list[WorkCard]) -> str:
    reached = [
        phase.name for phase in _PHASES
        if any(_PHASE_BY_KIND.get(c.kind) == phase.name for c in cards)
    ]
    return reached[-1] if reached else _PHASES[0].name


def stage_of(phase: str) -> str:
    """The stage grouping *phase* belongs to."""
    return _STAGE_BY_PHASE.get(phase, phase)


#: Card states that mean a phase waits on the operator, not on work.
_WAITING_STATES = frozenset({"awaiting_human", "quarantined"})


def phase_statuses(cards: list[WorkCard]) -> list[tuple[str, str]]:
    """Every phase, in order, with its status (feature 034): ``done``,
    ``active``, ``waiting``, ``problem``, ``skipped``, ``cancelled`` or
    ``upcoming``.

    Still display-only. A phase with no cards is ``skipped`` once the
    request has moved past it (or reached its end), and ``upcoming``
    otherwise — so a failed or cancelled request never reads as a
    completed path (feature 040). A cancelled request's last phase reads
    ``cancelled``: that is where it stopped.
    """
    by_phase: dict[str, list[WorkCard]] = {p.name: [] for p in _PHASES}
    for card in cards:
        if card.kind in _PHASE_BY_KIND:
            by_phase[_PHASE_BY_KIND[card.kind]].append(card)
    names = [p.name for p in _PHASES]
    outcome = outcome_of(cards)
    reached = [i for i, name in enumerate(names) if by_phase[name]]
    last_reached = max(reached, default=-1)
    statuses = [
        (name, _status(by_phase[name], outcome == DONE or i < last_reached))
        for i, name in enumerate(names)
    ]
    if outcome == CANCELLED and last_reached >= 0:
        statuses[last_reached] = (names[last_reached], "cancelled")
    return statuses


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

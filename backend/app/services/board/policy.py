"""Pure board policy: state transitions and dependency-graph validation.

This module is the deterministic authority behind every board mutation
(FR-005): it has no persistence, routing, or adapter dependencies, so the
same rules apply identically to interactive interventions, coordinator
actions, and recovery.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from app.models_board import CardRelation, CardState, RelationKind

#: Allowed-origins table from data-model.md's "Card States" section.
#: Quarantine is entered only at input intake (never via transition) but is
#: exited by an operator release (-> ready) or discard (-> cancelled).
#: Terminal states accept no further transition; downstream invalidation
#: acts on the *other*, not-yet-terminal cards, not on a terminal one.
_ALLOWED_TRANSITIONS: dict[CardState, frozenset[CardState]] = {
    CardState.READY: frozenset(
        {
            CardState.CLAIMED,
            CardState.WAITING_DEPENDENCY,
            CardState.AWAITING_HUMAN,
            CardState.CANCELLED,
        }
    ),
    CardState.CLAIMED: frozenset(
        {
            CardState.REVIEW,
            CardState.READY,
            CardState.FAILED,
            CardState.CANCELLED,
        }
    ),
    CardState.WAITING_DEPENDENCY: frozenset(
        # AWAITING_HUMAN: an unblocked ``manual_task`` is the operator's
        # move, never claimable work (feature 031, research R4).
        {CardState.READY, CardState.AWAITING_HUMAN, CardState.CANCELLED}
    ),
    CardState.AWAITING_HUMAN: frozenset(
        # READY resumes claimable work paused for a human answer; DONE is
        # a gate's own approval (no specialist ever claims a gate card,
        # so "validated completion" is the human decision itself).
        {CardState.READY, CardState.DONE, CardState.CANCELLED}
    ),
    CardState.REVIEW: frozenset(
        {CardState.DONE, CardState.FAILED, CardState.CANCELLED}
    ),
    CardState.QUARANTINED: frozenset(
        {CardState.READY, CardState.CANCELLED}
    ),
    CardState.DONE: frozenset(),
    # No automatic path ever re-opens a failed card — only an explicit
    # operator retry/cancel intervention does (FR-032), which is why this
    # edge exists in the graph but nothing in the automatic coordinator/
    # claim flow ever proposes it.
    CardState.FAILED: frozenset({CardState.READY, CardState.CANCELLED}),
    CardState.CANCELLED: frozenset(),
}


class PolicyViolation(Exception):
    """Raised when a board mutation would violate deterministic policy."""


class CycleError(PolicyViolation):
    """Raised when a candidate relation would introduce a cycle."""

    def __init__(self, cycle: tuple[str, ...]) -> None:
        """
        :param cycle: The card ids forming the rejected cycle, in order.
        """
        self.cycle = cycle
        super().__init__(
            f"relation would introduce a cycle: {' -> '.join(cycle)}"
        )


def is_valid_transition(current: CardState, target: CardState) -> bool:
    """Whether *current* may transition directly to *target*."""
    return target in _ALLOWED_TRANSITIONS[current]


def validate_new_relation(
    existing: Iterable[CardRelation], candidate: CardRelation
) -> None:
    """Raise :class:`CycleError` if adding *candidate* is unsafe.

    Rejects a self-edge outright, then rejects any relation (of any kind)
    that would close a cycle when combined with *existing* relations
    (data-model.md: "self-edge and cycle forbidden").

    :param existing: The workflow's current relations.
    :param candidate: The relation being added.
    """
    if candidate.card_id == candidate.depends_on_card_id:
        raise CycleError((candidate.card_id, candidate.card_id))
    graph: dict[str, list[str]] = {}
    for relation in (*existing, candidate):
        graph.setdefault(relation.card_id, []).append(
            relation.depends_on_card_id
        )
    cycle = _find_cycle(graph, candidate.card_id)
    if cycle is not None:
        raise CycleError(tuple(cycle))


def _find_cycle(graph: Mapping[str, list[str]], start: str) -> list[str] | None:
    """Depth-first search from *start* for the first cycle back to it."""
    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []
    return _visit(graph, start, visiting, visited, path)


def _visit(
    graph: Mapping[str, list[str]],
    node: str,
    visiting: set[str],
    visited: set[str],
    path: list[str],
) -> list[str] | None:
    """One DFS step; returns the closing cycle path, if *node* revisits it."""
    if node in visiting:
        return [*path[path.index(node):], node]
    if node in visited:
        return None
    visiting.add(node)
    path.append(node)
    for neighbour in graph.get(node, ()):
        found = _visit(graph, neighbour, visiting, visited, path)
        if found is not None:
            return found
    visiting.discard(node)
    visited.add(node)
    path.pop()
    return None


def dependencies_met(
    card_id: str,
    relations: Iterable[CardRelation],
    states: Mapping[str, CardState],
) -> bool:
    """Whether every ``dependency``-kind upstream card for *card_id* is done.

    Successful dependency completion is what moves a dependent card toward
    ``ready`` (data-model.md); non-dependency relations (reconciliation,
    supersedes) never gate readiness.

    :param card_id: The card whose dependencies are being checked.
    :param relations: The workflow's relations.
    :param states: Current state of every card, keyed by card id.
    """
    for relation in relations:
        if (
            relation.card_id != card_id
            or relation.kind != RelationKind.DEPENDENCY
        ):
            continue
        if states.get(relation.depends_on_card_id) != CardState.DONE:
            return False
    return True

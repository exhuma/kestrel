"""When a workflow's work is ready to deliver (feature 031, research R7).

One request delivers through one branch and one change request, so a
clean verification requests delivery only once *all* of the workflow's
coding work is settled — not on the first clean verification, as before
feature 031. Delivery still only ever follows a clean verification, so
nothing unverified is pushed.

Manual cards never count: they block the request's completion, not its
delivery (FR-008).
"""
from __future__ import annotations

import hashlib

from app.models_board import (
    TERMINAL_STATES,
    CardKind,
    CardRelation,
    CardState,
    RelationKind,
    WorkCard,
)

#: Kinds whose open (or failed) cards mean the code is not settled yet.
_SETTLING_KINDS = frozenset(
    {
        CardKind.IMPLEMENTATION.value,
        CardKind.VERIFICATION.value,
        CardKind.RECONCILIATION.value,
        CardKind.COORDINATOR_REVIEW.value,
    }
)


def delivery_due(
    cards: list[WorkCard], relations: list[CardRelation]
) -> bool:
    """Whether a clean verification should now request delivery.

    True when no implementation, verification, reconciliation or
    coordinator-review card is still open or ``failed``, and every
    ``done`` implementation card of an approved CAB-2 task has a
    ``done`` verification depending on it. Coordinator-created work
    carries no such edge, so for it the clean verification that calls
    this is the only evidence, as before. A breakdown with only manual
    tasks never has a verification to call this at all (FR-015).
    """
    if any(_unsettled(card) for card in cards):
        return False
    return _tagged_done_ids(cards) <= _verified_ids(cards, relations)


def delivery_trigger(cards: list[WorkCard]) -> str:
    """An idempotency key for delivering exactly this finished work.

    Stable for one set of ``done`` implementation cards, and new once a
    later one (e.g. a CI repair) joins it — so each distinct set of
    finished work delivers once.
    """
    ids = ",".join(sorted(_done_implementation_ids(cards)))
    return f"delivery:{hashlib.sha256(ids.encode()).hexdigest()[:16]}"


def _done_implementation_ids(cards: list[WorkCard]) -> set[str]:
    return {
        c.id for c in cards
        if c.kind == CardKind.IMPLEMENTATION.value
        and c.state == CardState.DONE.value
    }


def _tagged_done_ids(cards: list[WorkCard]) -> set[str]:
    done = _done_implementation_ids(cards)
    return {c.id for c in cards if c.id in done and c.task_node_id}


def _unsettled(card: WorkCard) -> bool:
    if card.kind not in _SETTLING_KINDS:
        return False
    state = CardState(card.state)
    return state not in TERMINAL_STATES or state == CardState.FAILED


def _verified_ids(
    cards: list[WorkCard], relations: list[CardRelation]
) -> set[str]:
    """Ids of cards some ``done`` verification card depends on."""
    done_verifications = {
        c.id for c in cards
        if c.kind == CardKind.VERIFICATION.value
        and c.state == CardState.DONE.value
    }
    return {
        r.depends_on_card_id for r in relations
        if r.kind == RelationKind.DEPENDENCY
        and r.card_id in done_verifications
    }

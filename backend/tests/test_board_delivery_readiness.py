"""Tests for when a workflow's work is ready to deliver (feature 031,
research R7): one request, one delivery."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.models_board import CardRelation, RelationKind, WorkCard
from app.services.board.delivery_readiness import (
    delivery_due,
    delivery_trigger,
)
from app.services.board.dispatch_delivery import _request_delivery
from tests.test_board_decomposition import _setup


def _card(
    card_id: str, kind: str, state: str, node: str | None = "t1"
) -> WorkCard:
    return WorkCard(
        id=card_id, workflow_id="wf-1", kind=kind, title=card_id,
        state=state, task_node_id=node,
    )


def _checks(verification: str, implementation: str) -> CardRelation:
    return CardRelation(
        card_id=verification, depends_on_card_id=implementation,
        kind=RelationKind.DEPENDENCY,
    )


_DONE_TASK = [
    _card("impl-1", "implementation", "done"),
    _card("ver-1", "verification", "done"),
]
_EDGES = [_checks("ver-1", "impl-1")]


def test_a_verified_task_is_due() -> None:
    assert delivery_due(_DONE_TASK, _EDGES) is True


def test_another_task_still_in_progress_holds_delivery() -> None:
    """Ensure the first clean verification does not deliver (FR-012)."""
    cards = [*_DONE_TASK, _card("impl-2", "implementation", "ready", "t2")]

    assert delivery_due(cards, _EDGES) is False


def test_a_failed_card_holds_delivery() -> None:
    cards = [*_DONE_TASK, _card("ver-2", "verification", "failed", "t2")]

    assert delivery_due(cards, _EDGES) is False


def test_an_open_escalation_holds_delivery() -> None:
    cards = [*_DONE_TASK, _card("rev", "coordinator_review", "ready")]

    assert delivery_due(cards, _EDGES) is False


def test_an_approved_task_without_its_verification_is_not_due() -> None:
    """Ensure nothing an approved task built is pushed unverified."""
    cards = [
        *_DONE_TASK,
        _card("fix", "implementation", "done"),
    ]

    assert delivery_due(cards, _EDGES) is False


def test_an_open_manual_task_never_holds_delivery() -> None:
    """Ensure manual work blocks completion, not delivery (FR-008)."""
    cards = [*_DONE_TASK, _card("man", "manual_task", "awaiting_human", "t2")]

    assert delivery_due(cards, _EDGES) is True


def test_coordinator_work_needs_no_edge() -> None:
    """Ensure pre-031 flows (no task, no edge) deliver as before."""
    cards = [
        _card("impl", "implementation", "done", None),
        _card("ver", "verification", "done", None),
    ]

    assert delivery_due(cards, []) is True


def test_the_trigger_changes_only_with_the_finished_work() -> None:
    later = [*_DONE_TASK, _card("ci", "implementation", "done", None)]

    assert delivery_trigger(_DONE_TASK) == delivery_trigger(
        list(reversed(_DONE_TASK))
    )
    assert delivery_trigger(later) != delivery_trigger(_DONE_TASK)


def _deliveries(store) -> list[WorkCard]:
    return [c for c in store.list_cards("wf-1") if c.kind == "delivery"]


def test_one_delivery_per_set_of_finished_work(tmp_path: Path) -> None:
    """Ensure repeated clean verifications deliver once, and a later fix
    (e.g. a CI repair) delivers once more (FR-013)."""
    store, coordinator, *_ = _setup(tmp_path)
    store.set_card_state("card-1", "cancelled")
    for card in _DONE_TASK:
        store.create_card(card)
    store.add_relation(_EDGES[0], created_by_action="test")
    services = SimpleNamespace(
        claims=SimpleNamespace(store=store), coordinator=coordinator
    )

    _request_delivery("wf-1", services)
    _request_delivery("wf-1", services)
    assert len(_deliveries(store)) == 1

    store.set_card_state(_deliveries(store)[0].id, "done")
    store.create_card(_card("ci", "implementation", "done", None))
    _request_delivery("wf-1", services)
    second_delivery = 2
    assert len(_deliveries(store)) == second_delivery

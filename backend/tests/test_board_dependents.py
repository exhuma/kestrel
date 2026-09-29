"""Tests for the dependency-ready cascade (feature 026; feature 031's
manual-task target state)."""
from __future__ import annotations

from pathlib import Path

from app.models_board import (
    CardRelation,
    RelationKind,
    WorkCard,
    Workflow,
)
from app.persistence.board_store import BoardStore
from app.services.board.dependents import advance_ready_dependents
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory


def _board(tmp_path: Path) -> tuple[BoardStore, BoardService]:
    """A workflow with one done prerequisite and two waiting dependents."""
    store = BoardStore(board_session_factory(tmp_path))
    store.create_workflow(
        Workflow(
            id="wf-1", source="github-issue", task_ref="o/r#1", repo="o/r",
            base_branch="main", source_visibility="public", title="t",
        )
    )
    cards = [
        ("prereq", "implementation", "done"),
        ("impl", "implementation", "waiting_dependency"),
        ("manual", "manual_task", "waiting_dependency"),
    ]
    for card_id, kind, state in cards:
        store.create_card(
            WorkCard(
                id=card_id, workflow_id="wf-1", kind=kind, title=card_id,
                state=state,
            )
        )
    for dependent in ("impl", "manual"):
        store.add_relation(
            CardRelation(
                card_id=dependent,
                depends_on_card_id="prereq",
                kind=RelationKind.DEPENDENCY,
            ),
            created_by_action="test",
        )
    return store, BoardService(store)


def test_an_unblocked_manual_task_awaits_the_operator(tmp_path: Path) -> None:
    """Ensure a manual task goes to awaiting_human, never to ready."""
    store, service = _board(tmp_path)

    advance_ready_dependents(store, service, "wf-1")

    assert store.get_card("manual").state == "awaiting_human"


def test_an_unblocked_implementation_card_becomes_ready(
    tmp_path: Path,
) -> None:
    """Ensure every other kind still becomes ready."""
    store, service = _board(tmp_path)

    advance_ready_dependents(store, service, "wf-1")

    assert store.get_card("impl").state == "ready"

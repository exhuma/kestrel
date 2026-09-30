"""Tests for coordinator-routed, capped PRD redraft (feature 028)."""
from __future__ import annotations

from pathlib import Path

from app.models_board import CardKind, WorkCard, Workflow
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_store import BoardStore
from app.services.board.coordinator import CoordinatorService
from app.services.board.prd_redraft import maybe_redraft_prd
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory

_WORKFLOW = Workflow(
    id="wf-1", source="github-issue", task_ref="owner/repo#1",
    repo="owner/repo", base_branch="main", source_visibility="public",
    title="Add a thing",
)


def _setup(tmp_path: Path) -> tuple[BoardStore, CoordinatorService]:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    board_service = BoardService(store)
    coordinator = CoordinatorService(
        store, BoardCoordinatorStore(factory), board_service,
    )
    store.create_workflow(_WORKFLOW)
    return store, coordinator


def _prd_gate(card_id: str = "gate-1") -> WorkCard:
    return WorkCard(
        id=card_id, workflow_id="wf-1", kind=CardKind.PRD_GATE.value,
        title="Approve PRD", state="cancelled",
    )


class TestMaybeRedraftPrd:
    def test_no_coordinator_falls_back_to_a_direct_redraft(
        self, tmp_path: Path
    ) -> None:
        store, _coordinator = _setup(tmp_path)
        gate = _prd_gate()
        store.create_card(gate)

        maybe_redraft_prd(gate, store, None, redraft_cap=1)

        new_cards = [c for c in store.list_cards("wf-1") if c.id != gate.id]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "prd"
        assert new_cards[0].eligible_roles == ("pm",)

    def test_under_the_cap_asks_the_coordinator_to_triage(
        self, tmp_path: Path
    ) -> None:
        store, coordinator = _setup(tmp_path)
        gate = _prd_gate()
        store.create_card(gate)

        maybe_redraft_prd(gate, store, coordinator, redraft_cap=1)

        new_cards = [c for c in store.list_cards("wf-1") if c.id != gate.id]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "coordinator_review"
        assert new_cards[0].source_card_id == gate.id
        assert gate.id in new_cards[0].title
        assert not any(c.kind == "prd" for c in new_cards)

    def test_at_the_cap_escalates_instead_of_asking_for_triage(
        self, tmp_path: Path
    ) -> None:
        store, coordinator = _setup(tmp_path)
        store.create_card(_prd_gate("gate-1"))
        store.create_card(_prd_gate("gate-2"))
        latest = _prd_gate("gate-3")
        store.create_card(latest)

        maybe_redraft_prd(latest, store, coordinator, redraft_cap=1)

        new_cards = [
            c for c in store.list_cards("wf-1")
            if c.id not in {"gate-1", "gate-2", "gate-3"}
        ]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "coordinator_review"
        assert "exhausted" in new_cards[0].title.lower()

    def test_non_prd_gate_is_a_no_op(self, tmp_path: Path) -> None:
        store, coordinator = _setup(tmp_path)
        other = WorkCard(
            id="gate-1", workflow_id="wf-1",
            kind=CardKind.UNDERSTANDING_GATE.value,
            title="Confirm understanding", state="done",
        )
        store.create_card(other)

        maybe_redraft_prd(other, store, coordinator, redraft_cap=1)

        assert store.list_cards("wf-1") == [other]

    def test_triage_request_is_idempotent_per_gate(
        self, tmp_path: Path
    ) -> None:
        store, coordinator = _setup(tmp_path)
        gate = _prd_gate()
        store.create_card(gate)

        maybe_redraft_prd(gate, store, coordinator, redraft_cap=1)
        maybe_redraft_prd(gate, store, coordinator, redraft_cap=1)

        new_cards = [c for c in store.list_cards("wf-1") if c.id != gate.id]
        assert len(new_cards) == 1

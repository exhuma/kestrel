"""Tests for multi-round refinement-interview bookkeeping (feature 028).

Unit-tests the free functions directly (not through ``GatesService``) —
they take their collaborators explicitly, so a full ``GatesService``
isn't needed to exercise them.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models_board import CardKind, WorkCard, Workflow
from app.models_board_records import HumanGateRecord
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.refinement_rounds import (
    has_any_round,
    maybe_advance_round,
    round_context,
    still_pending,
)
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory

_ROUND_TWO_COUNT = 2

_WORKFLOW = Workflow(
    id="wf-1", source="github-issue", task_ref="owner/repo#1",
    repo="owner/repo", base_branch="main", source_visibility="public",
    title="Add a thing",
)


@dataclass(frozen=True)
class _Collab:
    store: BoardStore
    gate_store: BoardGateStore
    artifacts: ArtifactsService


def _setup(tmp_path: Path) -> _Collab:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    gate_store = BoardGateStore(factory)
    board_service = BoardService(store)
    artifacts = ArtifactsService(
        store, BoardArtifactStore(factory), board_service,
        BoardArtifactContentStore(tmp_path / "artifacts"),
    )
    store.create_workflow(_WORKFLOW)
    return _Collab(store, gate_store, artifacts)


def _refinement_card(
    card_id: str, persona: str, state: str = "review"
) -> WorkCard:
    return WorkCard(
        id=card_id, workflow_id="wf-1", kind=CardKind.REFINEMENT.value,
        title=f"{persona} interview questions", state=state,
        eligible_roles=(persona,),
    )


def _linked_gate(
    collab: _Collab, gate_id: str, origin_card_id: str, state: str = "done",
) -> WorkCard:
    """A ``refinement_gate`` whose target artifact links back to
    *origin_card_id*, mirroring what ``route_refinement_result`` sets up
    for real (this module recovers a gate's persona through that
    linkage, not from the gate card itself)."""
    artifact = collab.artifacts.store_reference_artifact(
        ArtifactDraft(
            producer_card_id=origin_card_id, logical_name="questions",
            revision=1, content='{"questions": ["q?"]}', trust="agent_output",
        )
    )
    gate = WorkCard(
        id=gate_id, workflow_id="wf-1", kind=CardKind.REFINEMENT_GATE.value,
        title="interview", state=state,
    )
    collab.store.create_card(gate)
    collab.gate_store.create_gate(
        HumanGateRecord(
            id=f"{gate_id}-record", card_id=gate_id,
            requested_decision="answer", target_artifact_id=artifact.id,
        )
    )
    if state == "done":
        collab.artifacts.store_reference_artifact(
            ArtifactDraft(
                producer_card_id=gate_id, logical_name="response",
                revision=1, content="an answer", trust="operator_approved",
            )
        )
    return collab.store.get_card(gate_id)


class TestMaybeAdvanceRound:
    def test_creates_round_two_when_under_the_cap(
        self, tmp_path: Path
    ) -> None:
        collab = _setup(tmp_path)
        collab.store.create_card(_refinement_card("card-1", "requester"))
        gate = _linked_gate(collab, "gate-1", "card-1")

        maybe_advance_round(
            gate, collab.store, collab.gate_store.get_for_card,
            collab.artifacts, round_cap=2,
        )

        new_rounds = [
            c for c in collab.store.list_cards("wf-1")
            if c.kind == CardKind.REFINEMENT.value
        ]
        assert len(new_rounds) == _ROUND_TWO_COUNT
        assert new_rounds[1].eligible_roles == ("requester",)
        assert new_rounds[1].state == "ready"

    def test_stops_at_the_round_cap(self, tmp_path: Path) -> None:
        collab = _setup(tmp_path)
        collab.store.create_card(_refinement_card("card-1", "requester"))
        gate = _linked_gate(collab, "gate-1", "card-1")

        maybe_advance_round(
            gate, collab.store, collab.gate_store.get_for_card,
            collab.artifacts, round_cap=1,
        )

        rounds = [
            c for c in collab.store.list_cards("wf-1")
            if c.kind == CardKind.REFINEMENT.value
        ]
        assert len(rounds) == 1

    def test_no_op_for_a_gate_with_no_linked_origin_card(
        self, tmp_path: Path
    ) -> None:
        collab = _setup(tmp_path)
        gate = WorkCard(
            id="gate-1", workflow_id="wf-1",
            kind=CardKind.REFINEMENT_GATE.value, title="interview",
            state="done",
        )
        collab.store.create_card(gate)

        maybe_advance_round(
            gate, collab.store, collab.gate_store.get_for_card,
            collab.artifacts, round_cap=5,
        )

        cards = collab.store.list_cards("wf-1")
        assert not any(c.kind == CardKind.REFINEMENT.value for c in cards)


class TestStillPending:
    def test_pending_while_an_ungated_round_is_in_flight(
        self, tmp_path: Path
    ) -> None:
        collab = _setup(tmp_path)
        collab.store.create_card(
            _refinement_card("card-1", "requester", state="ready")
        )

        assert still_pending(
            collab.store.list_cards("wf-1"), collab.gate_store.get_for_card,
            collab.artifacts,
        )

    def test_resolved_gate_is_not_pending_even_though_origin_stays_review(
        self, tmp_path: Path
    ) -> None:
        collab = _setup(tmp_path)
        collab.store.create_card(_refinement_card("card-1", "requester"))
        _linked_gate(collab, "gate-1", "card-1", state="done")

        assert not still_pending(
            collab.store.list_cards("wf-1"), collab.gate_store.get_for_card,
            collab.artifacts,
        )

    def test_pending_while_the_gate_is_still_awaiting_human(
        self, tmp_path: Path
    ) -> None:
        collab = _setup(tmp_path)
        collab.store.create_card(_refinement_card("card-1", "requester"))
        _linked_gate(collab, "gate-1", "card-1", state="awaiting_human")

        assert still_pending(
            collab.store.list_cards("wf-1"), collab.gate_store.get_for_card,
            collab.artifacts,
        )


class TestHasAnyRound:
    def test_false_when_nothing_created_yet(self, tmp_path: Path) -> None:
        collab = _setup(tmp_path)
        assert has_any_round(collab.store.list_cards("wf-1")) is False

    def test_true_once_a_refinement_card_exists(self, tmp_path: Path) -> None:
        collab = _setup(tmp_path)
        collab.store.create_card(_refinement_card("card-1", "requester"))
        assert has_any_round(collab.store.list_cards("wf-1")) is True


class TestRoundContext:
    def test_states_the_round_number_and_cap(self, tmp_path: Path) -> None:
        collab = _setup(tmp_path)
        card = _refinement_card("card-1", "requester")
        collab.store.create_card(card)

        context = round_context(
            card, collab.store.list_cards("wf-1"),
            collab.gate_store.get_for_card, collab.artifacts, round_cap=3,
        )

        assert "round 1 of 3" in context

    def test_final_round_instructs_consolidation(self, tmp_path: Path) -> None:
        collab = _setup(tmp_path)
        card = _refinement_card("card-1", "requester")
        collab.store.create_card(card)

        context = round_context(
            card, collab.store.list_cards("wf-1"),
            collab.gate_store.get_for_card, collab.artifacts, round_cap=1,
        )

        assert "final round" in context.lower()
        # The final round still asks; it never swaps a question for an
        # assumption (feature 037).
        assert "ask now everything" in context
        assert "do not ask" not in context.lower()

    def test_includes_the_personas_own_prior_round_answer(
        self, tmp_path: Path
    ) -> None:
        collab = _setup(tmp_path)
        collab.store.create_card(_refinement_card("card-1", "requester"))
        _linked_gate(collab, "gate-1", "card-1", state="done")
        round_two = _refinement_card("card-2", "requester")
        collab.store.create_card(round_two)

        context = round_context(
            round_two, collab.store.list_cards("wf-1"),
            collab.gate_store.get_for_card, collab.artifacts, round_cap=2,
        )

        assert "an answer" in context

"""The understanding step: a restatement to confirm or correct
(feature 032, #67)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models_board import WorkCard
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactsService
from app.services.board.coordinator import CoordinatorService, CreateCardAction
from app.services.board.gates import GatesService
from app.services.board.retries import UnreadableResultError
from app.services.board.understanding import (
    RESTATEMENT_LOGICAL_NAME,
    route_understanding_result,
    understanding_context,
)
from app.services.board.understanding_redraft import understanding_card
from tests.test_board_decomposition import _setup

_RESTATEMENT = "<UNDERSTANDING>You want a CSV export.</UNDERSTANDING>"


class _Flow:
    """A workflow at its understanding step."""

    def __init__(self, tmp_path: Path) -> None:
        store, coordinator, gates, artifacts, _card, gate_store = _setup(
            tmp_path
        )
        self.store: BoardStore = store
        self.coordinator: CoordinatorService = coordinator
        self.gates: GatesService = gates
        self.artifacts: ArtifactsService = artifacts
        self.gate_store = gate_store

    def draft(self, text: str = _RESTATEMENT) -> WorkCard:
        """Have pm answer a fresh understanding card with *text*."""
        card = understanding_card("wf-1")
        self.store.create_card(card)
        self.store.set_card_state(card.id, "done")  # its result accepted
        route_understanding_result(
            text, card, self.gates, self.artifacts
        )
        return card

    def open_gate(self) -> WorkCard:
        (gate,) = [
            c for c in self.store.list_cards("wf-1")
            if c.kind == "understanding_gate" and c.state == "awaiting_human"
        ]
        return gate

    def kinds(self) -> list[str]:
        return [c.kind for c in self.store.list_cards("wf-1")]


def test_the_gate_opens_on_the_restatement(tmp_path: Path) -> None:
    """Ensure the operator confirms something that is actually there."""
    flow = _Flow(tmp_path)
    draft = flow.draft()

    gate = flow.open_gate()
    target = flow.gate_store.get_for_card(gate.id).target_artifact_id
    assert flow.artifacts.read_document(target).plain_text() == (
        "You want a CSV export."
    )
    assert flow.artifacts.producer_card_id(target) == draft.id
    assert flow.gate_store.get_for_card(gate.id).requested_decision == (
        "confirm_understanding"
    )


def test_an_unreadable_restatement_opens_no_gate(tmp_path: Path) -> None:
    """Ensure no empty understanding gate is ever shown (FR-010): the
    result is reported unreadable, to be tried again (feature 042)."""
    flow = _Flow(tmp_path)

    with pytest.raises(UnreadableResultError):
        flow.draft("I think it is about exports.")

    assert "understanding_gate" not in flow.kinds()


def test_a_rejection_redrafts_with_the_correction(tmp_path: Path) -> None:
    """Ensure the redraft sees what was wrong and what to change."""
    flow = _Flow(tmp_path)
    flow.draft()

    flow.gates.resolve(
        flow.open_gate().id, "rejected", answer="It is a PDF export."
    )

    (redraft,) = [
        c for c in flow.store.list_cards("wf-1")
        if c.kind == "understanding" and c.state == "ready"
    ]
    assert redraft.title == "Redraft the understanding"
    context = understanding_context(redraft, flow.store, flow.artifacts)
    assert "You want a CSV export." in context
    assert "It is a PDF export." in context


def test_a_first_draft_gets_no_redraft_context(tmp_path: Path) -> None:
    flow = _Flow(tmp_path)
    card = understanding_card("wf-1")
    flow.store.create_card(card)

    assert understanding_context(card, flow.store, flow.artifacts) == ""


def test_past_the_cap_a_rejection_opens_a_review(tmp_path: Path) -> None:
    """Ensure repeated rejections stop redrafting (SC-004): the default
    cap allows two redrafts, so the third rejection escalates."""
    flow = _Flow(tmp_path)
    flow.draft()
    for _round in range(3):
        flow.gates.resolve(flow.open_gate().id, "rejected", answer="No.")
        pending = [
            c for c in flow.store.list_cards("wf-1")
            if c.kind == "understanding" and c.state == "ready"
        ]
        if not pending:
            break
        flow.store.set_card_state(pending[0].id, "done")
        route_understanding_result(
            _RESTATEMENT, pending[0], flow.gates, flow.artifacts,
        )

    drafts_allowed = 3
    assert flow.kinds().count("understanding") == drafts_allowed
    reviews = [
        c for c in flow.store.list_cards("wf-1")
        if c.kind == "coordinator_review"
    ]
    assert [r.title for r in reviews] == [
        "Understanding not confirmed after 3 drafts"
    ]


def test_the_coordinator_cannot_create_an_understanding_card(
    tmp_path: Path,
) -> None:
    flow = _Flow(tmp_path)

    (record,) = flow.coordinator.apply_actions(
        "wf-1", "x", [CreateCardAction(kind="understanding", title="Mine")]
    )

    assert record.validation_decision == "rejected"


def test_the_restatement_is_stored_under_its_own_name(
    tmp_path: Path,
) -> None:
    flow = _Flow(tmp_path)
    draft = flow.draft()

    content = flow.artifacts.latest_document_for_card(
        draft.id, RESTATEMENT_LOGICAL_NAME
    )
    assert content.plain_text() == "You want a CSV export."

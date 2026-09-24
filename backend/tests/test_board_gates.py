"""Human-gate revision, decision provenance, PRD scope, and targeted
invalidation tests for ``GatesService`` (feature 026, T043).

A gate card is never claimed by a specialist (data-model.md "Card
States"); its own approval or rejection is the only way it leaves
``awaiting_human``, and a rejection must invalidate only the work that
actually depended on it, not the whole workflow (User Story 4, Scenario
2-3).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models_board import CardRelation, WorkCard, Workflow
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.services.board.gates import GatesService, UnknownGateError
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory

_WORKFLOW = Workflow(
    id="wf-1",
    source="github-issue",
    task_ref="owner/repo#1",
    repo="owner/repo",
    base_branch="main",
    source_visibility="public",
    title="Add a thing",
)




def _service(tmp_path: Path) -> tuple[GatesService, BoardStore]:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    board_service = BoardService(store)
    gate_store = BoardGateStore(factory)
    store.create_workflow(_WORKFLOW)
    return GatesService(store, gate_store, board_service), store


class TestGateCreation:
    """Creating a gate produces an awaiting_human card and its record."""

    def test_creates_an_awaiting_human_card(self, tmp_path: Path) -> None:
        service, store = _service(tmp_path)

        card = service.create_gate(
            "wf-1",
            kind="understanding_gate",
            title="Confirm understanding",
            requested_decision="Approve the restated understanding?",
        )

        assert card.state == "awaiting_human"
        assert store.get_card(card.id).state == "awaiting_human"


class TestApproval:
    """Approving a gate completes it and cascades ready dependents."""

    def test_approval_moves_the_gate_to_done(self, tmp_path: Path) -> None:
        service, _store = _service(tmp_path)
        card = service.create_gate(
            "wf-1",
            kind="understanding_gate",
            title="Confirm understanding",
            requested_decision="Approve?",
        )

        resolved = service.resolve(card.id, "approved")

        assert resolved.state == "done"

    def test_approval_makes_a_waiting_dependent_ready(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        gate = service.create_gate(
            "wf-1",
            kind="understanding_gate",
            title="Confirm understanding",
            requested_decision="Approve?",
        )
        store.create_card(
            WorkCard(
                id="card-2",
                workflow_id="wf-1",
                kind="analysis",
                title="Investigate",
                state="waiting_dependency",
            )
        )
        store.add_relation(CardRelation("card-2", gate.id))

        service.resolve(gate.id, "approved")

        assert store.get_card("card-2").state == "ready"

    def test_decision_is_recorded_for_provenance(
        self, tmp_path: Path
    ) -> None:
        service, _store = _service(tmp_path)
        card = service.create_gate(
            "wf-1",
            kind="understanding_gate",
            title="Confirm understanding",
            requested_decision="Approve?",
        )

        service.resolve(card.id, "approved")

        record = service.get_gate(card.id)
        assert record.decision == "approved"
        assert record.requested_decision == "Approve?"


class TestPrdScope:
    """A PRD gate's decision references the exact artifact it approves."""

    def test_approval_records_the_target_artifact(
        self, tmp_path: Path
    ) -> None:
        service, _store = _service(tmp_path)
        card = service.create_gate(
            "wf-1",
            kind="prd_gate",
            title="Approve PRD",
            requested_decision="Approve the PRD?",
            target_artifact_id="artifact-prd-1",
        )

        service.resolve(card.id, "approved")

        record = service.get_gate(card.id)
        assert record.target_artifact_id == "artifact-prd-1"


class TestRejection:
    """A rejection invalidates only the work that depended on this gate."""

    def test_rejection_cancels_the_gate(self, tmp_path: Path) -> None:
        service, _store = _service(tmp_path)
        card = service.create_gate(
            "wf-1",
            kind="understanding_gate",
            title="Confirm understanding",
            requested_decision="Approve?",
        )

        resolved = service.resolve(card.id, "rejected")

        assert resolved.state == "cancelled"

    def test_rejection_cancels_only_directly_dependent_work(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        gate = service.create_gate(
            "wf-1",
            kind="understanding_gate",
            title="Confirm understanding",
            requested_decision="Approve?",
        )
        store.create_card(
            WorkCard(
                id="dependent",
                workflow_id="wf-1",
                kind="analysis",
                title="Depends on gate",
                state="waiting_dependency",
            )
        )
        store.add_relation(CardRelation("dependent", gate.id))
        store.create_card(
            WorkCard(
                id="unrelated",
                workflow_id="wf-1",
                kind="analysis",
                title="Unrelated work",
                state="ready",
            )
        )

        service.resolve(gate.id, "rejected")

        assert store.get_card("dependent").state == "cancelled"
        assert store.get_card("unrelated").state == "ready"

    def test_rejection_does_not_cancel_already_terminal_dependents(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        gate = service.create_gate(
            "wf-1",
            kind="understanding_gate",
            title="Confirm understanding",
            requested_decision="Approve?",
        )
        store.create_card(
            WorkCard(
                id="already-done",
                workflow_id="wf-1",
                kind="analysis",
                title="Already finished",
                state="done",
            )
        )
        store.add_relation(CardRelation("already-done", gate.id))

        service.resolve(gate.id, "rejected")

        assert store.get_card("already-done").state == "done"


class TestUnknownGate:
    """Resolving a card with no gate record is rejected."""

    def test_resolving_unknown_card_raises(self, tmp_path: Path) -> None:
        service, _store = _service(tmp_path)
        with pytest.raises(UnknownGateError):
            service.resolve("missing", "approved")

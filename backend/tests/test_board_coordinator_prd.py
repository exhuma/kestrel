"""PRD-gate coordinator-side enforcement tests (feature 026, T078).

Split out of ``test_board_coordinator.py`` to keep that module under the
repo's 500-line ceiling, mirroring the existing
``test_board_gates``/``test_board_gates_prd`` split.
"""
from __future__ import annotations

from pathlib import Path

from app.models_board import WorkCard
from app.services.board.coordinator import CreateCardAction
from tests.test_board_coordinator import _coordinator


class TestPrdGateEnforcement:
    """T078: with board_prd_gate_required on, only analysis/refinement/
    prd/coordinator_review cards may be created until a prd_gate for
    this workflow reaches done — this blocks decomposition too, not
    just design/implementation, since PRD must resolve first."""

    def test_a_design_card_is_rejected_while_prd_is_pending(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path, prd_gate_required=True)

        results = coordinator.apply_actions(
            "wf-1", "trigger-1",
            [CreateCardAction(kind="design", title="Design it")],
        )

        assert results[0].validation_decision == "rejected"
        assert "PRD gate required" in results[0].rejection_reason
        assert not results[0].applied
        assert [c.title for c in store.list_cards("wf-1")] == ["Investigate"]

    def test_decomposition_is_also_rejected_while_prd_is_pending(
        self, tmp_path: Path
    ) -> None:
        """PRD comes before decomposition when both are required — unlike
        decomposition's own exemption set, decomposition is not exempt
        from PRD enforcement."""
        coordinator, store = _coordinator(tmp_path, prd_gate_required=True)

        results = coordinator.apply_actions(
            "wf-1", "trigger-1",
            [
                CreateCardAction(
                    kind="decomposition", title="Decompose",
                    eligible_roles=("pm",),
                )
            ],
        )

        assert results[0].validation_decision == "rejected"

    def test_analysis_refinement_and_prd_cards_are_still_allowed(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path, prd_gate_required=True)

        coordinator.apply_actions(
            "wf-1", "trigger-1",
            [
                CreateCardAction(kind="analysis", title="More analysis"),
                CreateCardAction(
                    kind="refinement", title="Interview",
                    eligible_roles=("pm",),
                ),
                CreateCardAction(
                    kind="prd", title="Draft PRD", eligible_roles=("pm",),
                ),
            ],
        )

        titles = {c.title for c in store.list_cards("wf-1")}
        assert {"More analysis", "Interview", "Draft PRD"} <= titles

    def test_a_design_card_is_allowed_once_prd_gate_is_done(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path, prd_gate_required=True)
        store.create_card(
            WorkCard(
                id="gate-1", workflow_id="wf-1", kind="prd_gate",
                title="Approve PRD", state="done",
            )
        )

        coordinator.apply_actions(
            "wf-1", "trigger-1",
            [CreateCardAction(kind="design", title="Design it")],
        )

        titles = {c.title for c in store.list_cards("wf-1")}
        assert "Design it" in titles

    def test_not_yet_done_gate_still_blocks(self, tmp_path: Path) -> None:
        coordinator, store = _coordinator(tmp_path, prd_gate_required=True)
        store.create_card(
            WorkCard(
                id="gate-1", workflow_id="wf-1", kind="prd_gate",
                title="Approve PRD", state="awaiting_human",
            )
        )

        results = coordinator.apply_actions(
            "wf-1", "trigger-1",
            [CreateCardAction(kind="design", title="Design it")],
        )

        assert results[0].validation_decision == "rejected"

    def test_disabled_by_default_allows_design_immediately(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path)

        coordinator.apply_actions(
            "wf-1", "trigger-1",
            [CreateCardAction(kind="design", title="Design it")],
        )

        titles = {c.title for c in store.list_cards("wf-1")}
        assert "Design it" in titles

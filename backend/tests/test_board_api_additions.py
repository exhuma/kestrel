"""Tests for the four additive board-API fields (feature 029, T005):
decomposition parent link, human title, interview round/cap, and the
cap-exhausted marker.

See ``specs/029-workflow-visualisation/contracts/board-api-additions.md``.
Unlike ``test_board_views.py`` (stubbed ``GatesService``/``ChildTaskStore``
boundaries), this drives ``workflow_summary``/``GatesService.gate_round``
against real, store-backed collaborators — the integration seam these four
additions actually depend on.
"""
from __future__ import annotations

from pathlib import Path

from app.models_board import WorkCard, Workflow
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.persistence.child_task_store import ChildTaskStore
from app.routers.board_views import workflow_summary
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.gates import GateRequirements, GatesService
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory

_ROUND_CAP = 2

_WORKFLOW = Workflow(
    id="wf-1", source="github-issue", task_ref="owner/repo#1",
    repo="owner/repo", base_branch="main", source_visibility="public",
    title="Add CSV export",
)


def _rig(
    tmp_path: Path, *, round_cap: int = 1
) -> tuple[GatesService, BoardStore, ChildTaskStore]:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    board_service = BoardService(store)
    artifacts = ArtifactsService(
        store, BoardArtifactStore(factory), board_service,
        BoardArtifactContentStore(tmp_path / "artifacts"),
    )
    gates = GatesService(
        store, BoardGateStore(factory), board_service, artifacts,
        required=GateRequirements(refinement_round_cap=round_cap),
    )
    store.create_workflow(_WORKFLOW)
    return gates, store, ChildTaskStore(factory)


def _questions_artifact(card_id: str) -> ArtifactDraft:
    return ArtifactDraft(
        producer_card_id=card_id, logical_name="questions", revision=1,
        content='{"questions": ["q?"]}', trust="agent_output",
    )


def _refinement_card(card_id: str) -> WorkCard:
    return WorkCard(
        id=card_id, workflow_id="wf-1", kind="refinement",
        title="pm interview questions", state="done",
        eligible_roles=("pm",),
    )


class TestParentLink:
    """A1 (FR-040): the decomposition parent, nullable."""

    def test_null_for_an_ordinary_request(self, tmp_path: Path) -> None:
        gates, store, child_tasks = _rig(tmp_path)
        summary = workflow_summary(
            _WORKFLOW, store.list_cards("wf-1"), gates, child_tasks
        )
        assert summary.parent_workflow_id is None

    def test_set_for_a_decomposed_child(self, tmp_path: Path) -> None:
        gates, store, child_tasks = _rig(tmp_path)
        child_tasks.record(
            parent_workflow_id="wf-parent", task_ref="owner/repo#1"
        )
        summary = workflow_summary(
            _WORKFLOW, store.list_cards("wf-1"), gates, child_tasks
        )
        assert summary.parent_workflow_id == "wf-parent"


class TestTitle:
    """A2 (FR-041): present on the listing row, falling back when unset."""

    def test_title_present(self, tmp_path: Path) -> None:
        gates, store, child_tasks = _rig(tmp_path)
        summary = workflow_summary(
            _WORKFLOW, store.list_cards("wf-1"), gates, child_tasks
        )
        assert summary.title == "Add CSV export"

    def test_falls_back_to_task_label_when_unrecorded(
        self, tmp_path: Path
    ) -> None:
        gates, store, child_tasks = _rig(tmp_path)
        untitled = Workflow(**{**_WORKFLOW.__dict__, "title": ""})
        summary = workflow_summary(untitled, [], gates, child_tasks)
        assert summary.title == "owner/repo#1"


class TestRoundAndCap:
    """A3 (FR-042): {round, cap} on a refinement_gate's detail."""

    def test_null_for_a_non_capped_gate(self, tmp_path: Path) -> None:
        gates, store, _child_tasks = _rig(tmp_path)
        gate = gates.create_gate(
            "wf-1", kind="prd_gate", title="Approve PRD",
            requested_decision="approve_prd",
        )
        assert gates.gate_round(gate, store.list_cards("wf-1")) is None

    def test_populated_for_a_capped_gate(self, tmp_path: Path) -> None:
        gates, store, _child_tasks = _rig(tmp_path, round_cap=_ROUND_CAP)
        store.create_card(_refinement_card("card-r1"))
        artifact = gates._artifacts.store_reference_artifact(
            _questions_artifact("card-r1")
        )
        gate = gates.create_gate(
            "wf-1", kind="refinement_gate", title="Answer round 1",
            requested_decision="answer", target_artifact_id=artifact.id,
        )
        cards = store.list_cards("wf-1")
        assert gates.gate_round(gate, cards) == 1
        assert gates.refinement_round_cap == _ROUND_CAP


class TestCapExhausted:
    """A4 (FR-043): whether a round cap was hit without a usable answer."""

    def test_false_normally(self, tmp_path: Path) -> None:
        gates, store, child_tasks = _rig(tmp_path, round_cap=_ROUND_CAP)
        store.create_card(_refinement_card("card-r1"))
        artifact = gates._artifacts.store_reference_artifact(
            _questions_artifact("card-r1")
        )
        gates.create_gate(
            "wf-1", kind="refinement_gate", title="Answer round 1",
            requested_decision="answer", target_artifact_id=artifact.id,
        )
        summary = workflow_summary(
            _WORKFLOW, store.list_cards("wf-1"), gates, child_tasks
        )
        assert summary.cap_exhausted is False

    def test_true_once_the_final_round_gate_still_awaits(
        self, tmp_path: Path
    ) -> None:
        gates, store, child_tasks = _rig(tmp_path, round_cap=_ROUND_CAP)
        store.create_card(_refinement_card("card-r1"))
        store.create_card(_refinement_card("card-r2"))
        artifact = gates._artifacts.store_reference_artifact(
            _questions_artifact("card-r2")
        )
        gates.create_gate(
            "wf-1", kind="refinement_gate", title="Answer round 2",
            requested_decision="answer", target_artifact_id=artifact.id,
        )
        summary = workflow_summary(
            _WORKFLOW, store.list_cards("wf-1"), gates, child_tasks
        )
        assert summary.cap_exhausted is True

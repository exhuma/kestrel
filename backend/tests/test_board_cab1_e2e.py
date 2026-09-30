"""End-to-end test for the CAB-1 strategic fit gate (feature 027,
GitHub #47).

Mirrors ``test_board_refinement_e2e.py``'s style: drives the real
dispatch loop rather than constructing gates directly, so it exercises
the same production path a bug could hide in — this is exactly the gap
GitHub #42's post-mortem noted (unit tests that build a gate directly
never exercise the deterministic-trigger wiring a real approval walks
through).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.backends.base import TurnRequest, TurnResult
from app.models_board import SpecialistDefinition, Workflow
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactsService
from app.services.board.claims import ClaimsService
from app.services.board.coordinator import CoordinatorService
from app.services.board.dispatch_ready import (
    DispatchServices,
    dispatch_ready_work,
)
from app.services.board.gates import GateRequirements, GatesService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from tests.board_test_support import board_session_factory

_STRATEGIC_QUESTIONS = (
    '<REFINEMENT_QUESTIONS>{"questions": '
    '["Why does this matter to the business?"]}</REFINEMENT_QUESTIONS>'
)

_WORKFLOW = Workflow(
    id="wf-1", source="github-issue", task_ref="owner/repo#1",
    repo="owner/repo", base_branch="main", source_visibility="public",
    title="Add CSV export", task_body="Users need to export data as CSV.",
)


class _FixedBackend:
    """Always returns the same strategic-interview question set."""

    async def run_turn(self, req: TurnRequest) -> TurnResult:
        assert "Kind: strategic_interview" in req.prompt
        return TurnResult(session_id="turn-1", final_text=_STRATEGIC_QUESTIONS)


def _persona(role_id: str, *card_types: str) -> SpecialistDefinition:
    return SpecialistDefinition(
        id=role_id, label=role_id, purpose="test role",
        allowed_card_types=card_types, required_abilities=(),
        model_policy="default", workspace_permission="read_only",
        retry_limit=1, prompt=f"You are {role_id}.",
    )


def _stack(tmp_path: Path, *, cab1: bool) -> tuple[
    GatesService, BoardStore, DispatchServices
]:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    claims_store = BoardClaimsStore(factory)
    coordinator_store = BoardCoordinatorStore(factory)
    gate_store = BoardGateStore(factory)
    artifact_store = BoardArtifactStore(factory)
    content_store = BoardArtifactContentStore(tmp_path / "artifacts")
    board_service = BoardService(store)
    artifacts = ArtifactsService(
        store, artifact_store, board_service, content_store
    )
    coordinator = CoordinatorService(store, coordinator_store, board_service)
    gates = GatesService(
        store, gate_store, board_service, artifacts,
        required=GateRequirements(prd=True, cab1=cab1),
    )
    roster = SpecialistRoster({
        "requester": _persona(
            "requester", "refinement", "strategic_interview"
        ),
        "pm": _persona("pm", "refinement", "prd"),
        "uiux": _persona("uiux", "refinement"),
    })
    store.create_workflow(_WORKFLOW)
    claims = ClaimsService(
        store=store, claims_store=claims_store, roster=roster,
        max_parallel_read_cards=4, default_lease_seconds=60,
        default_workspace_lease_seconds=600,
    )
    services = DispatchServices(
        claims, roster, artifacts, coordinator=coordinator, gates=gates,
    )
    return gates, store, services


class TestCab1EnabledFullChain:
    @pytest.mark.asyncio
    async def test_understanding_to_refinement_via_cab1(
        self, tmp_path: Path
    ) -> None:
        gates, store, services = _stack(tmp_path, cab1=True)

        understanding = gates.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )
        gates.resolve(understanding.id, "approved")
        interviews = [
            c for c in store.list_cards("wf-1")
            if c.kind == "strategic_interview"
        ]
        assert len(interviews) == 1
        assert interviews[0].eligible_roles == ("requester",)

        await dispatch_ready_work(
            "wf-1", services, lambda _s: _FixedBackend(), timeout_seconds=5
        )
        interview_gates = [
            c for c in store.list_cards("wf-1")
            if c.kind == "strategic_interview_gate"
        ]
        assert len(interview_gates) == 1

        gates.resolve(
            interview_gates[0].id, "approved",
            answer=(
                "Q: Why does this matter to the business?\n"
                "A: It unblocks Q3 reporting for finance."
            ),
        )
        cab1_gates = [
            c for c in store.list_cards("wf-1") if c.kind == "cab1_gate"
        ]
        assert len(cab1_gates) == 1
        assert cab1_gates[0].state == "awaiting_human"

        gates.resolve(cab1_gates[0].id, "approved")
        # The coordinator now plans who is interviewed (feature 038).
        plans = [
            c for c in store.list_cards("wf-1") if c.kind == "interview_plan"
        ]
        assert len(plans) == 1

    @pytest.mark.asyncio
    async def test_rejecting_cab1_leaves_prior_history_intact(
        self, tmp_path: Path
    ) -> None:
        gates, store, services = _stack(tmp_path, cab1=True)

        understanding = gates.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )
        gates.resolve(understanding.id, "approved")
        await dispatch_ready_work(
            "wf-1", services, lambda _s: _FixedBackend(), timeout_seconds=5
        )
        interview_gate = next(
            c for c in store.list_cards("wf-1")
            if c.kind == "strategic_interview_gate"
        )
        gates.resolve(
            interview_gate.id, "approved",
            answer="Q: Why does this matter to the business?\nA: Because X.",
        )
        cab1_gate = next(
            c for c in store.list_cards("wf-1") if c.kind == "cab1_gate"
        )

        gates.resolve(cab1_gate.id, "rejected")

        kinds = {c.kind for c in store.list_cards("wf-1")}
        assert "interview_plan" not in kinds
        assert {
            "understanding_gate", "strategic_interview",
            "strategic_interview_gate", "cab1_gate",
        } <= kinds
        terminal = {"done", "cancelled", "failed"}
        for card in store.list_cards("wf-1"):
            if card.kind != "cab1_gate":
                assert card.state in terminal


class TestCab1DisabledByDefault:
    @pytest.mark.asyncio
    async def test_understanding_to_refinement_unchanged(
        self, tmp_path: Path
    ) -> None:
        gates, store, _services = _stack(tmp_path, cab1=False)

        understanding = gates.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )
        gates.resolve(understanding.id, "approved")

        kinds = [c.kind for c in store.list_cards("wf-1")]
        assert kinds == ["understanding_gate", "interview_plan"]

"""End-to-end test for the full refinement-interview → PRD → approval
flow through the real dispatch loop (feature 026, T078).

Unlike ``test_board_refinement.py`` (unit-level parsing/routing) and
``test_board_gates_prd.py`` (``GatesService`` in isolation), this drives
the whole sequence the way it actually happens: ``understanding_gate``
approval deterministically creates the three interview cards,
``dispatch_ready_work`` claims and turns each one, an operator answers
each ``refinement_gate``, the last answer deterministically creates
`pm`'s ``prd`` card, another dispatch pass drafts and routes it, and
approving the resulting ``prd_gate`` records ``Workflow.approved_prd``.
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

_INTERVIEW_PERSONA_COUNT = 3

_WORKFLOW = Workflow(
    id="wf-1", source="github-issue", task_ref="owner/repo#1",
    repo="owner/repo", base_branch="main", source_visibility="public",
    title="Add CSV export", task_body="Users need to export data as CSV.",
)


class _KindAwareBackend:
    """Returns a fixed result per card kind, read from the envelope
    (the only thing distinguishing turns dispatched to the same
    specialist across different cards in this test)."""

    def __init__(self, by_kind: dict[str, str]) -> None:
        self._by_kind = by_kind

    async def run_turn(self, req: TurnRequest) -> TurnResult:
        for kind, text in self._by_kind.items():
            if f"Kind: {kind}" in req.prompt:
                return TurnResult(session_id="turn-1", final_text=text)
        raise AssertionError(f"unexpected envelope: {req.prompt!r}")


def _persona(role_id: str, *card_types: str) -> SpecialistDefinition:
    return SpecialistDefinition(
        id=role_id, label=role_id, purpose="test role",
        allowed_card_types=card_types, required_abilities=(),
        model_policy="default", workspace_permission="read_only",
        retry_limit=1, prompt=f"You are {role_id}.",
    )


class TestFullRefinementToPrdFlow:
    @pytest.mark.asyncio
    async def test_understanding_to_approved_prd(
        self, tmp_path: Path
    ) -> None:
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
        coordinator = CoordinatorService(
            store, coordinator_store, board_service
        )
        gates = GatesService(
            store, gate_store, board_service, artifacts,
            required=GateRequirements(prd=True),
        )
        roster = SpecialistRoster({
            "requester": _persona("requester", "refinement"),
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
        backend = _KindAwareBackend({
            "refinement": (
                '<REFINEMENT_QUESTIONS>{"questions": '
                '["What is the deadline?"]}</REFINEMENT_QUESTIONS>'
            ),
            "prd": "<PRD>Implement CSV export behind a feature flag.</PRD>",
        })

        understanding = gates.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )
        gates.resolve(understanding.id, "approved")

        # Pass 1: each persona's refinement card is claimed and turned,
        # creating one refinement_gate per persona.
        await dispatch_ready_work(
            "wf-1", services, lambda _s: backend, timeout_seconds=5
        )
        interview_gates = [
            c for c in store.list_cards("wf-1") if c.kind == "refinement_gate"
        ]
        assert len(interview_gates) == _INTERVIEW_PERSONA_COUNT

        # An operator answers each interview; the last answer
        # deterministically creates pm's prd card.
        for gate in interview_gates:
            gates.resolve(
                gate.id, "approved",
                answer="Q: What is the deadline?\nA: Ship by Friday.",
            )
        assert any(c.kind == "prd" for c in store.list_cards("wf-1"))

        # Pass 2: pm's prd card is claimed and turned, creating prd_gate.
        await dispatch_ready_work(
            "wf-1", services, lambda _s: backend, timeout_seconds=5
        )
        prd_gates = [
            c for c in store.list_cards("wf-1") if c.kind == "prd_gate"
        ]
        assert len(prd_gates) == 1

        gates.resolve(prd_gates[0].id, "approved")

        workflow = store.get_workflow("wf-1")
        assert (
            workflow.approved_prd
            == "Implement CSV export behind a feature flag."
        )

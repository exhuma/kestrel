"""A full board stack for the coordinator-run interview (feature 038)."""
from __future__ import annotations

from pathlib import Path

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
from app.services.board.dispatch_ready import DispatchServices
from app.services.board.gates import GateRequirements, GatesService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from tests.board_test_support import board_session_factory

WORKFLOW = Workflow(
    id="wf-1", source="github-issue", task_ref="owner/repo#1",
    repo="owner/repo", base_branch="main", source_visibility="public",
    title="Add CSV export", task_body="Users need to export data as CSV.",
)


def specialist(role_id: str, *card_types: str) -> SpecialistDefinition:
    return SpecialistDefinition(
        id=role_id, label=role_id.upper(), purpose=f"{role_id} expertise",
        allowed_card_types=card_types, required_abilities=(),
        model_policy="default", workspace_permission="read_only",
        retry_limit=1, prompt=f"You are {role_id}.",
    )


def interview_stack(tmp_path: Path):
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    board_service = BoardService(store)
    artifacts = ArtifactsService(
        store, BoardArtifactStore(factory), board_service,
        BoardArtifactContentStore(tmp_path / "artifacts"),
    )
    gates = GatesService(
        store, BoardGateStore(factory), board_service, artifacts,
        required=GateRequirements(prd=True),
    )
    roster = SpecialistRoster({
        "coordinator": specialist(
            "coordinator", "interview_plan", "question_review"
        ),
        "pm": specialist("pm", "refinement", "prd"),
        "dba": specialist("dba", "refinement"),
        "infosec": specialist("infosec", "refinement"),
    })
    store.create_workflow(WORKFLOW)
    claims = ClaimsService(
        store=store, claims_store=BoardClaimsStore(factory), roster=roster,
        max_parallel_read_cards=4, default_lease_seconds=60,
        default_workspace_lease_seconds=600,
    )
    coordinator = CoordinatorService(
        store, BoardCoordinatorStore(factory), board_service
    )
    services = DispatchServices(
        claims, roster, artifacts, coordinator=coordinator, gates=gates,
    )
    return services, store, gates, artifacts

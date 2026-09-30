"""Regression test for GitHub #42: intake's initial understanding gate
must be resolvable, not just creatable.

Every other gate test builds its gate with ``GatesService.create_gate``
directly (``test_board_gates.py``), a path production intake never
takes. This test instead drives the real production entry point
(``IngestionService.maybe_start_run``) with real ``BoardService``,
``GatesService`` and ``InterventionsService`` instances, and resolves
the resulting card through ``InterventionsService.apply`` — the same
call the ``/interventions`` router route makes, and the one that used
to raise ``InvalidInterventionError`` (HTTP 422) because intake never
wrote a ``HumanGateRecord``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.config_models import TaskSourceConfig
from app.models_board import CardAction
from app.models_board_records import IntakeOutcome
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.persistence.dismissal_store import DismissalStore
from app.ports import Task
from app.services.board.artifacts import ArtifactsService
from app.services.board.gates import GatesService
from app.services.board.interventions import (
    GateResolution,
    InterventionsService,
)
from app.services.board.quarantine import ExistingWorkflowIntake
from app.services.board.service import BoardService
from app.services.board.understanding import route_understanding_result
from app.services.ingestion import BoardIntake, IngestionService
from tests.board_test_support import board_session_factory


class _FakeTaskSource:
    """Releases a fixed, harmless body — quarantine screening itself is
    exercised elsewhere (``test_board_input_intake.py``)."""

    async def get_task(self, ref: str) -> Task:
        return Task(ref=ref, title="Add a thing", body="Do the thing.")

    def visibility(self) -> str:
        return "public"


class _FakeTaskSources:
    def __init__(self) -> None:
        self.sources = {"github-issue": _FakeTaskSource()}
        self.code_hosts: dict[str, object] = {}


class _FakeQuarantine:
    """Always releases — the fail-closed boundary is not what's under
    test here."""

    async def intake_for_existing_workflow(
        self, intake: ExistingWorkflowIntake
    ) -> IntakeOutcome:
        return IntakeOutcome(released=True, safe_content=intake.content)


@pytest.mark.asyncio
async def test_intake_gate_resolves_through_interventions(
    tmp_path: Path,
) -> None:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    claims_store = BoardClaimsStore(factory)
    gate_store = BoardGateStore(factory)
    artifact_store = BoardArtifactStore(factory)
    content_store = BoardArtifactContentStore(tmp_path / "artifacts")
    board_service = BoardService(store)
    artifacts = ArtifactsService(
        store, artifact_store, board_service, content_store
    )
    gates = GatesService(store, gate_store, board_service, artifacts)
    interventions = InterventionsService(
        store, claims_store, board_service, gates
    )

    settings = Settings(
        task_sources=[
            TaskSourceConfig(type="github", watched_repos=["owner/repo"])
        ],
    )
    ingestion = IngestionService(
        settings,
        _FakeTaskSources(),
        DismissalStore(factory),
        BoardIntake(_FakeQuarantine(), board_service),
    )

    workflow_id = await ingestion.maybe_start_run(
        source="github-issue",
        task_ref="owner/repo#1",
        code_repo="owner/repo",
    )
    assert workflow_id is not None

    # Since feature 032 the gate opens on pm's restatement.
    (draft,) = [
        c for c in store.list_cards(workflow_id) if c.kind == "understanding"
    ]
    store.set_card_state(draft.id, "done")
    route_understanding_result(
        "<UNDERSTANDING>You want a thing.</UNDERSTANDING>", draft,
        gates, artifacts,
    )
    cards = store.list_cards(workflow_id)
    gate_cards = [c for c in cards if c.kind == "understanding_gate"]
    assert len(gate_cards) == 1
    gate_card = gate_cards[0]
    assert gates.get_gate(gate_card.id) is not None

    workflow = store.get_workflow(workflow_id)
    resolved = interventions.apply(
        workflow_id,
        gate_card.id,
        CardAction.RESOLVE_GATE,
        expected_revision=workflow.revision,
        resolution=GateResolution(decision="approved"),
    )

    assert resolved.state == "done"

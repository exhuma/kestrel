"""Tests for the board collection/snapshot/card/intervention routes
(feature 026, T053/T058).

Exercises the additive ``/api/board/workflows...`` surface end-to-end
against a real, migrated SQLite-backed board (not fakes) — these routes
assemble several stores together, so the integration seams are exactly
what's worth covering here.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.main import create_app
from app.models_board import (
    ClaimRequest,
    SpecialistDefinition,
    WorkCard,
    Workflow,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.services.board.bootstrap import (
    get_board_artifact_store,
    get_board_claims_store,
    get_board_service,
    get_interventions_service,
    get_specialist_roster,
)
from app.services.board.gates import GatesService
from app.services.board.interventions import InterventionsService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
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

_Client = tuple[httpx.AsyncClient, BoardStore, BoardClaimsStore]




def _specialist(role_id: str) -> SpecialistDefinition:
    return SpecialistDefinition(
        id=role_id,
        label=role_id.capitalize(),
        purpose="test role",
        allowed_card_types=("analysis",),
        required_abilities=(),
        model_policy="default",
        workspace_permission="read_only",
        retry_limit=1,
        prompt="do the thing",
    )


def _client(tmp_path: Path) -> _Client:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    claims_store = BoardClaimsStore(factory)
    artifact_store = BoardArtifactStore(factory)
    gate_store = BoardGateStore(factory)
    board_service = BoardService(store)
    gates_service = GatesService(store, gate_store, board_service)
    interventions_service = InterventionsService(
        store, claims_store, board_service, gates_service
    )
    roster = SpecialistRoster({"developer": _specialist("developer")})
    store.create_workflow(_WORKFLOW)

    app = create_app()
    app.dependency_overrides[get_board_service] = lambda: board_service
    app.dependency_overrides[get_specialist_roster] = lambda: roster
    app.dependency_overrides[get_board_claims_store] = lambda: claims_store
    app.dependency_overrides[get_board_artifact_store] = lambda: artifact_store
    app.dependency_overrides[get_interventions_service] = (
        lambda: interventions_service
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    return client, store, claims_store


def _ready_card(card_id: str = "card-1", **overrides: object) -> WorkCard:
    fields: dict[str, object] = {
        "id": card_id,
        "workflow_id": "wf-1",
        "kind": "analysis",
        "title": "Investigate",
        "state": "ready",
    }
    fields.update(overrides)
    return WorkCard(**fields)


@pytest.mark.asyncio
async def test_list_workflows_returns_the_summary_row(
    tmp_path: Path,
) -> None:
    client, store, _claims = _client(tmp_path)
    store.create_card(_ready_card())
    async with client as c:
        resp = await c.get("/api/board/workflows")
    assert resp.status_code == httpx.codes.OK
    body = resp.json()
    assert body == [
        {
            "id": "wf-1",
            "task_label": "owner/repo#1",
            "status": "active",
            "state_counts": {"ready": 1},
            "action_required_count": 0,
        }
    ]


@pytest.mark.asyncio
async def test_get_board_returns_the_full_snapshot(tmp_path: Path) -> None:
    client, store, _claims = _client(tmp_path)
    store.create_card(_ready_card(eligible_roles=("developer",)))
    async with client as c:
        resp = await c.get("/api/board/workflows/wf-1/board")
    assert resp.status_code == httpx.codes.OK
    body = resp.json()
    assert body["id"] == "wf-1"
    assert body["revision"] == 1
    assert len(body["cards"]) == 1
    assert body["cards"][0]["eligible_roles"][0]["label"] == "Developer"


@pytest.mark.asyncio
async def test_get_board_unknown_workflow_is_404(tmp_path: Path) -> None:
    client, _store, _claims = _client(tmp_path)
    async with client as c:
        resp = await c.get("/api/board/workflows/missing/board")
    assert resp.status_code == httpx.codes.NOT_FOUND


@pytest.mark.asyncio
async def test_get_card_returns_its_summary(tmp_path: Path) -> None:
    client, store, _claims = _client(tmp_path)
    store.create_card(_ready_card())
    async with client as c:
        resp = await c.get("/api/board/workflows/wf-1/cards/card-1")
    assert resp.status_code == httpx.codes.OK
    assert resp.json()["id"] == "card-1"


@pytest.mark.asyncio
async def test_get_card_unknown_card_is_404(tmp_path: Path) -> None:
    client, _store, _claims = _client(tmp_path)
    async with client as c:
        resp = await c.get("/api/board/workflows/wf-1/cards/missing")
    assert resp.status_code == httpx.codes.NOT_FOUND


@pytest.mark.asyncio
async def test_intervention_cancels_a_ready_card(tmp_path: Path) -> None:
    client, store, _claims = _client(tmp_path)
    store.create_card(_ready_card())
    async with client as c:
        resp = await c.post(
            "/api/board/workflows/wf-1/cards/card-1/interventions",
            json={"action": "cancel", "expected_revision": 1},
        )
    assert resp.status_code == httpx.codes.OK
    assert resp.json()["state"] == "cancelled"


@pytest.mark.asyncio
async def test_intervention_stale_revision_is_409(tmp_path: Path) -> None:
    client, store, _claims = _client(tmp_path)
    store.create_card(_ready_card())
    async with client as c:
        resp = await c.post(
            "/api/board/workflows/wf-1/cards/card-1/interventions",
            json={"action": "cancel", "expected_revision": 99},
        )
    assert resp.status_code == httpx.codes.CONFLICT


@pytest.mark.asyncio
async def test_intervention_invalid_action_for_state_is_422(
    tmp_path: Path,
) -> None:
    client, store, _claims = _client(tmp_path)
    store.create_card(_ready_card())
    async with client as c:
        resp = await c.post(
            "/api/board/workflows/wf-1/cards/card-1/interventions",
            json={"action": "reassign", "expected_revision": 1},
        )
    assert resp.status_code == httpx.codes.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_intervention_unknown_card_is_404(tmp_path: Path) -> None:
    client, _store, _claims = _client(tmp_path)
    async with client as c:
        resp = await c.post(
            "/api/board/workflows/wf-1/cards/missing/interventions",
            json={"action": "cancel", "expected_revision": 1},
        )
    assert resp.status_code == httpx.codes.NOT_FOUND


@pytest.mark.asyncio
async def test_claimed_card_reports_owner_via_the_router(
    tmp_path: Path,
) -> None:
    client, store, claims_store = _client(tmp_path)
    store.create_card(_ready_card(eligible_roles=("developer",)))
    claims_store.claim_card(ClaimRequest("card-1", "developer", 600))
    async with client as c:
        resp = await c.get("/api/board/workflows/wf-1/cards/card-1")
    assert resp.json()["owner"]["specialist_id"] == "developer"


@pytest.mark.asyncio
async def test_board_events_unknown_workflow_is_404(tmp_path: Path) -> None:
    """Ensure streaming an unknown workflow's board is a clean 404,
    established before streaming starts (matches
    ``test_workflow_events_unknown_returns_404``'s convention for the old
    driver's own events route)."""
    client, _store, _claims = _client(tmp_path)
    async with client as c:
        resp = await c.get("/api/board/workflows/missing/board/events")
    assert resp.status_code == httpx.codes.NOT_FOUND

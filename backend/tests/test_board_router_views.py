"""Tests for the board collection/snapshot/card/intervention routes
(feature 026, T053/T058).

Exercises the additive ``/api/board/workflows...`` surface end-to-end
against a real, migrated SQLite-backed board (not fakes) — these routes
assemble several stores together, so the integration seams are exactly
what's worth covering here.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
from app.models_board_records import (
    BoardEventRecord,
    HandoffArtifact,
    HumanGateRecord,
)
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.persistence.child_task_store import (
    ChildTaskStore,
    get_child_task_store,
)
from app.services.board.artifacts import ArtifactsService
from app.services.board.bootstrap import (
    get_artifacts_service,
    get_board_artifact_store,
    get_board_claims_store,
    get_board_service,
    get_gates_service,
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
    artifacts = ArtifactsService(
        store, artifact_store, board_service,
        BoardArtifactContentStore(tmp_path / "artifacts"),
    )
    gates_service = GatesService(store, gate_store, board_service, artifacts)
    child_task_store = ChildTaskStore(factory)
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
    app.dependency_overrides[get_gates_service] = lambda: gates_service
    app.dependency_overrides[get_artifacts_service] = lambda: artifacts
    app.dependency_overrides[get_child_task_store] = lambda: child_task_store
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
            "title": "Add a thing",
            "parent_workflow_id": None,
            "status": "active",
            "state_counts": {"ready": 1},
            "action_required_count": 0,
            "phase": "Technical analysis",
            "stage": "Planning",
            "cap_exhausted": False,
            "open_manual_task_count": 0,
        }
    ]


@pytest.mark.asyncio
async def test_list_workflows_orders_newest_first(tmp_path: Path) -> None:
    client, store, _claims = _client(tmp_path)
    older = Workflow(
        id="wf-0", source="github-issue", task_ref="owner/repo#0",
        repo="owner/repo", base_branch="main", source_visibility="public",
        title="Older",
    )
    store.create_workflow(
        older, now=datetime(2020, 1, 1, tzinfo=timezone.utc)
    )
    store.create_card(_ready_card("card-0", workflow_id="wf-0"))
    store.create_card(_ready_card("card-1", workflow_id="wf-1"))
    async with client as c:
        resp = await c.get("/api/board/workflows")
    assert [w["id"] for w in resp.json()] == ["wf-1", "wf-0"]


@pytest.mark.asyncio
async def test_list_workflows_excludes_terminal_by_default(
    tmp_path: Path,
) -> None:
    client, store, _claims = _client(tmp_path)
    store.create_card(_ready_card(state="done"))
    async with client as c:
        default_resp = await c.get("/api/board/workflows")
        included_resp = await c.get(
            "/api/board/workflows", params={"include_completed": "true"}
        )
    assert default_resp.json() == []
    assert [w["id"] for w in included_resp.json()] == ["wf-1"]


@pytest.mark.asyncio
async def test_list_workflows_collapses_a_resolved_quarantine_placeholder(
    tmp_path: Path,
) -> None:
    """A quarantine placeholder that hosted a since-released ticket must
    not linger as a second board entry once the ticket's real workflow
    also exists (#45)."""
    client, store, _claims = _client(tmp_path)
    store.create_card(_ready_card())
    placeholder = Workflow(
        id="wf-quarantine-1",
        source="github-issue",
        task_ref="github-issue:owner/repo#1",
        repo="",
        base_branch="",
        source_visibility="private",
        title="Security review",
        state="quarantined",
    )
    store.create_workflow(placeholder)
    async with client as c:
        resp = await c.get("/api/board/workflows")
    assert [w["id"] for w in resp.json()] == ["wf-1"]


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
async def test_list_board_events_returns_history_oldest_first(
    tmp_path: Path,
) -> None:
    client, store, _claims = _client(tmp_path)
    store.create_card(_ready_card(eligible_roles=("developer",)))
    store.append_event(
        BoardEventRecord(workflow_id="wf-1", event_type="workflow.created")
    )
    store.append_event(
        BoardEventRecord(
            workflow_id="wf-1", event_type="card.claimed", card_id="card-1"
        )
    )
    async with client as c:
        resp = await c.get("/api/board/workflows/wf-1/events")
    assert resp.status_code == httpx.codes.OK
    body = resp.json()
    assert [e["event_type"] for e in body] == [
        "workflow.created", "card.claimed",
    ]
    assert body[0]["specialist"] is None
    assert body[1]["specialist"]["id"] == "developer"


@pytest.mark.asyncio
async def test_list_board_events_unknown_workflow_is_404(
    tmp_path: Path,
) -> None:
    client, _store, _claims = _client(tmp_path)
    async with client as c:
        resp = await c.get("/api/board/workflows/missing/events")
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
async def test_resolve_gate_with_an_answer_stores_it(tmp_path: Path) -> None:
    """T078: the answer field reaches GatesService, not just decision."""
    client, store, _claims = _client(tmp_path)
    factory = board_session_factory(tmp_path)
    store.create_card(
        WorkCard(
            id="card-1", workflow_id="wf-1", kind="refinement_gate",
            title="requester interview", state="awaiting_human",
        )
    )
    BoardGateStore(factory).create_gate(
        HumanGateRecord(
            id="gate-1", card_id="card-1", requested_decision="answer",
        )
    )
    async with client as c:
        resp = await c.post(
            "/api/board/workflows/wf-1/cards/card-1/interventions",
            json={
                "action": "resolve_gate", "expected_revision": 1,
                "decision": "approved", "answer": "Ship by Friday.",
            },
        )
    assert resp.status_code == httpx.codes.OK
    assert resp.json()["state"] == "done"


@pytest.mark.asyncio
async def test_card_summary_surfaces_gate_detail(tmp_path: Path) -> None:
    client, store, _claims = _client(tmp_path)
    factory = board_session_factory(tmp_path)
    store.create_card(
        WorkCard(
            id="card-1", workflow_id="wf-1", kind="understanding_gate",
            title="Confirm understanding", state="awaiting_human",
        )
    )
    BoardGateStore(factory).create_gate(
        HumanGateRecord(
            id="gate-1",
            card_id="card-1",
            requested_decision="confirm_understanding",
        )
    )
    async with client as c:
        resp = await c.get("/api/board/workflows/wf-1/cards/card-1")
    gate = resp.json()["gate"]
    assert gate["requested_decision"] == "confirm_understanding"
    assert gate["decision"] is None


@pytest.mark.asyncio
async def test_card_summary_gate_is_null_for_a_non_gate_card(
    tmp_path: Path,
) -> None:
    client, store, _claims = _client(tmp_path)
    store.create_card(_ready_card())
    async with client as c:
        resp = await c.get("/api/board/workflows/wf-1/cards/card-1")
    assert resp.json()["gate"] is None


def _record_artifact(
    tmp_path: Path, *, artifact_id: str, content: str, trust: str
) -> None:
    factory = board_session_factory(tmp_path)
    content_store = BoardArtifactContentStore(tmp_path / "artifacts")
    content_ref, content_hash = content_store.write(content)
    BoardArtifactStore(factory).record(
        HandoffArtifact(
            id=artifact_id,
            producer_card_id="card-1",
            logical_name="report",
            revision=1,
            content_ref=content_ref,
            content_hash=content_hash,
            trust=trust,
        )
    )


@pytest.mark.asyncio
async def test_get_artifact_content_round_trips(tmp_path: Path) -> None:
    client, _store, _claims = _client(tmp_path)
    _record_artifact(
        tmp_path,
        artifact_id="artifact-1",
        content="the PRD body",
        trust="agent_output",
    )
    async with client as c:
        resp = await c.get("/api/board/artifacts/artifact-1/content")
    assert resp.status_code == httpx.codes.OK
    assert resp.json() == {"content": "the PRD body", "trust": "agent_output"}


@pytest.mark.asyncio
async def test_get_artifact_content_unknown_artifact_is_404(
    tmp_path: Path,
) -> None:
    client, _store, _claims = _client(tmp_path)
    async with client as c:
        resp = await c.get("/api/board/artifacts/missing/content")
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

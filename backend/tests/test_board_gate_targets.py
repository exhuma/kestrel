"""A gate exposes what it asks about (#66): its target artifact, which
belongs to the card that produced it, never to the gate card itself."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models_board import WorkCard
from app.models_board_records import HandoffArtifact, HumanGateRecord
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_gate_store import BoardGateStore
from tests.board_test_support import board_session_factory
from tests.test_board_decomposition import _setup
from tests.test_board_router_views import _client


def _interview(tmp_path: Path, store) -> None:
    """A refinement card's questions, and the gate asking them."""
    factory = board_session_factory(tmp_path)
    content_ref, content_hash = BoardArtifactContentStore(
        tmp_path / "artifacts"
    ).write('{"questions": ["Who uses it?"]}')
    BoardArtifactStore(factory).record(
        HandoffArtifact(
            id="art-questions", producer_card_id="card-ref",
            logical_name="questions", revision=1,
            content_ref=content_ref, content_hash=content_hash,
            trust="agent_output",
        )
    )
    for card_id, kind, state in (
        ("card-ref", "refinement", "done"),
        ("card-gate", "refinement_gate", "awaiting_human"),
    ):
        store.create_card(
            WorkCard(
                id=card_id, workflow_id="wf-1", kind=kind,
                title="pm interview (1 question)", state=state,
            )
        )
    BoardGateStore(factory).create_gate(
        HumanGateRecord(
            id="gate-1", card_id="card-gate", requested_decision="answer",
            target_artifact_id="art-questions",
        )
    )


@pytest.mark.asyncio
async def test_an_interview_gate_exposes_its_questions(
    tmp_path: Path,
) -> None:
    """Ensure the interview view can reach the questions it must show."""
    client, store, _claims = _client(tmp_path)
    _interview(tmp_path, store)

    async with client as c:
        resp = await c.get("/api/board/workflows/wf-1/cards/card-gate")

    body = resp.json()
    assert body["latest_artifact"] is None
    assert body["gate"]["target_artifact"] == {
        "id": "art-questions", "label": "questions", "revision": 1,
    }


@pytest.mark.asyncio
async def test_a_gate_without_a_target_exposes_none(tmp_path: Path) -> None:
    client, store, _claims = _client(tmp_path)
    store.create_card(
        WorkCard(
            id="card-1", workflow_id="wf-1", kind="understanding_gate",
            title="Confirm understanding", state="awaiting_human",
        )
    )
    BoardGateStore(board_session_factory(tmp_path)).create_gate(
        HumanGateRecord(
            id="gate-1", card_id="card-1",
            requested_decision="confirm_understanding",
        )
    )

    async with client as c:
        resp = await c.get("/api/board/workflows/wf-1/cards/card-1")

    assert resp.json()["gate"]["target_artifact"] is None


def test_the_cab1_decision_targets_the_strategic_answers(
    tmp_path: Path,
) -> None:
    """Ensure CAB-1 is decided with the requester's answers in view."""
    store, _coordinator, gates, artifacts, _card, gate_store = _setup(
        tmp_path
    )
    interview = gates.create_gate(
        "wf-1", kind="strategic_interview_gate", title="Strategic fit",
        requested_decision="answer",
    )

    gates.resolve(interview.id, "approved", answer="It saves a day a week.")

    (cab1,) = [c for c in store.list_cards("wf-1") if c.kind == "cab1_gate"]
    target_id = gate_store.get_for_card(cab1.id).target_artifact_id
    assert target_id is not None
    assert artifacts.read_content(target_id) == "It saves a day a week."

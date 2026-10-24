"""A rejection says why, and a decision says who took it (feature 046,
T034, research R12).

"A rejection needs a reason" used to live only in the frontend. A reply
on the ticket reaches ``GatesService.resolve`` without passing through it,
so the backend now enforces the rule. And a decision taken from the
ticket is credited to its author in the decision event, which the feed
reads (``frontend/src/lib/personas.ts``).
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.models_board import CardKind, WorkCard
from app.models_board_records import HumanGateRecord
from app.persistence.board_gate_store import BoardGateStore
from app.services.board.gate_decision import Decider, ReasonRequiredError
from tests.announcement_support import WORKFLOW_ID, build_stack, open_gate
from tests.board_test_support import board_session_factory
from tests.test_board_router_views import _client

_JIRA = Decider("jira", "acc-reporter", "Rita Reporter", "jira-comment:1")


def _decision_events(stack) -> list:
    return [
        e for e in stack.store.list_events(WORKFLOW_ID)
        if e.event_type in ("gate.approved", "gate.rejected")
    ]


@pytest.mark.parametrize("kind, decision", [
    (CardKind.UNDERSTANDING_GATE, "confirm_understanding"),
    (CardKind.PRD_GATE, "approve_prd"),
])
@pytest.mark.parametrize("answer", [None, "", "   "])
def test_a_rejection_that_needs_a_reason_is_refused_without_one(
    tmp_path: Path, kind: CardKind, decision: str, answer: str | None
) -> None:
    """Ensure the understanding and the PRD cannot be rejected without
    saying why, and the gate stays open."""
    stack = build_stack(tmp_path)
    gate = open_gate(stack, kind, None, decision)

    with pytest.raises(ReasonRequiredError):
        stack.gates.resolve(gate.id, "rejected", answer=answer)

    assert stack.store.get_card(gate.id).state == "awaiting_human"
    assert stack.gates.get_gate(gate.id).decision is None


def test_a_cab_rejection_needs_no_reason(tmp_path: Path) -> None:
    """Ensure the rule is only for the decisions the next step works
    from."""
    stack = build_stack(tmp_path)
    gate = open_gate(
        stack, CardKind.CAB1_GATE, None, "approve_strategic_fit"
    )

    resolved = stack.gates.resolve(gate.id, "rejected")

    assert resolved.state == "cancelled"


def test_a_rejection_with_a_reason_is_accepted(tmp_path: Path) -> None:
    """Ensure a reasoned rejection still goes through."""
    stack = build_stack(tmp_path)
    gate = open_gate(
        stack, CardKind.UNDERSTANDING_GATE, None, "confirm_understanding"
    )

    resolved = stack.gates.resolve(
        gate.id, "rejected", answer="It must cover exports too."
    )

    assert resolved.state == "cancelled"


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_a_ticket_decision_records_who_decided_and_where(
    tmp_path: Path, decision: str
) -> None:
    """Ensure the decision event carries the decider for the feed."""
    stack = build_stack(tmp_path)
    gate = open_gate(
        stack, CardKind.CAB1_GATE, None, "approve_strategic_fit"
    )

    stack.gates.resolve(gate.id, decision, decided_by=_JIRA)

    (event,) = _decision_events(stack)
    assert event.event_type == f"gate.{decision}"
    assert json.loads(event.payload) == {
        "detail": "Rita Reporter decided via Jira",
        "channel": "jira",
        "account_id": "acc-reporter",
        "display_name": "Rita Reporter",
    }


def test_an_operator_decision_keeps_an_empty_payload(tmp_path: Path) -> None:
    """Ensure a UI decision is recorded as before: the operator's."""
    stack = build_stack(tmp_path)
    gate = open_gate(
        stack, CardKind.CAB1_GATE, None, "approve_strategic_fit"
    )

    stack.gates.resolve(gate.id, "approved")

    (event,) = _decision_events(stack)
    assert json.loads(event.payload) == {}


def test_a_decider_without_a_name_is_still_credited(tmp_path: Path) -> None:
    """Ensure the feed never shows an empty name."""
    stack = build_stack(tmp_path)
    gate = open_gate(
        stack, CardKind.CAB1_GATE, None, "approve_strategic_fit"
    )

    stack.gates.resolve(
        gate.id, "approved", decided_by=Decider("jira", "acc-x", "")
    )

    (event,) = _decision_events(stack)
    assert json.loads(event.payload)["detail"] == "Someone decided via Jira"


@pytest.mark.asyncio
async def test_a_reasonless_rejection_through_the_api_is_422(
    tmp_path: Path,
) -> None:
    """Ensure the rule reaches the API as an unprocessable request, and
    the gate stays open."""
    client, store, _claims = _client(tmp_path)
    store.create_card(WorkCard(
        id="card-1", workflow_id="wf-1", kind="understanding_gate",
        title="Confirm understanding", state="awaiting_human",
    ))
    BoardGateStore(board_session_factory(tmp_path)).create_gate(
        HumanGateRecord(
            id="gate-1", card_id="card-1",
            requested_decision="confirm_understanding",
        )
    )
    async with client as c:
        resp = await c.post(
            "/api/board/workflows/wf-1/cards/card-1/interventions",
            json={
                "action": "resolve_gate", "expected_revision": 1,
                "decision": "rejected",
            },
        )

    assert resp.status_code == httpx.codes.UNPROCESSABLE_ENTITY
    assert store.get_card("card-1").state == "awaiting_human"

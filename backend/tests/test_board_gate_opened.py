"""A gate opening is a board event (feature 046, T020, research R6).

``GatesService.create_gate`` used to write the card and the gate record
straight to the stores: no event, no revision bump, nothing for the ticket
to be told by. Each of the six places a gate is opened must now leave one
``gate.opened`` event and move the workflow's revision on.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models_board import CardKind, WorkCard
from app.services.board.estimation import route_estimation_result
from app.services.board.question_review import after_draft
from app.services.board.refinement import (
    route_prd_result,
    route_strategic_interview_result,
)
from app.services.board.understanding import route_understanding_result
from app.services.board.understanding_redraft import understanding_card
from tests.announcement_support import (
    WORKFLOW_ID,
    build_stack,
    open_gate,
)
from tests.test_board_estimation import (
    _CODING,
    _MANUAL,
    _estimates,
    _estimation_setup,
)
from tests.test_board_question_review import _drafted
from tests.test_board_question_review import _stack as _interview

_GATE_KINDS = [
    CardKind.UNDERSTANDING_GATE,
    CardKind.STRATEGIC_INTERVIEW_GATE,
    CardKind.REFINEMENT_GATE,
    CardKind.PRD_GATE,
    CardKind.CAB1_GATE,
    CardKind.DECOMPOSITION_GATE,
]
_ONE_EVENT = 1


def _opened(store) -> list:
    return [
        e for e in store.list_events(WORKFLOW_ID)
        if e.event_type == "gate.opened"
    ]


def _assert_one_opening(store, gate_kind: CardKind, revision: int) -> None:
    (event,) = _opened(store)
    gate = store.get_card(event.card_id)
    assert gate.kind == gate_kind.value
    assert json.loads(event.payload) == {"gate_kind": gate_kind.value}
    assert store.get_workflow(WORKFLOW_ID).revision > revision


@pytest.mark.parametrize("kind", _GATE_KINDS, ids=lambda k: k.value)
def test_create_gate_appends_an_event_and_bumps_the_revision(
    tmp_path: Path, kind: CardKind
) -> None:
    """Ensure every kind of gate announces its opening on the board."""
    stack = build_stack(tmp_path)
    revision = stack.store.get_workflow(WORKFLOW_ID).revision

    gate = open_gate(stack, kind, None, "decide")

    (event,) = _opened(stack.store)
    assert event.card_id == gate.id
    assert json.loads(event.payload) == {"gate_kind": kind.value}
    assert stack.store.get_workflow(WORKFLOW_ID).revision == revision + 1
    assert stack.opened == [WORKFLOW_ID]


def test_opening_a_gate_does_not_wake_the_coordinator(
    tmp_path: Path,
) -> None:
    """Ensure a gate for a human is not a change for the coordinator."""
    stack = build_stack(tmp_path)
    woken: list[str] = []
    stack.board._on_mutation = woken.append  # the scheduling hook

    open_gate(stack, CardKind.PRD_GATE, None, "approve_prd")

    assert woken == []


def test_the_understanding_gate_call_site(tmp_path: Path) -> None:
    """Ensure understanding.py opens its gate through the event."""
    stack = build_stack(tmp_path)
    revision = stack.store.get_workflow(WORKFLOW_ID).revision
    card = understanding_card(WORKFLOW_ID)
    stack.store.create_card(card)

    route_understanding_result(
        "<UNDERSTANDING>You want CSV.</UNDERSTANDING>", card, stack.gates,
        stack.artifacts,
    )

    _assert_one_opening(stack.store, CardKind.UNDERSTANDING_GATE, revision)


def test_the_strategic_interview_call_site(tmp_path: Path) -> None:
    """Ensure refinement.py opens the strategic interview through the
    event."""
    stack = build_stack(tmp_path)
    revision = stack.store.get_workflow(WORKFLOW_ID).revision
    card = WorkCard(
        id="card-si", workflow_id=WORKFLOW_ID,
        kind=CardKind.STRATEGIC_INTERVIEW.value, title="Strategic",
        state="done", attempt_count=1,
    )
    stack.store.create_card(card)

    route_strategic_interview_result(
        '<REFINEMENT_QUESTIONS>{"questions": ["Why now?"]}'
        "</REFINEMENT_QUESTIONS>",
        card, stack.gates, stack.artifacts,
    )

    _assert_one_opening(
        stack.store, CardKind.STRATEGIC_INTERVIEW_GATE, revision
    )


def test_the_prd_call_site(tmp_path: Path) -> None:
    """Ensure refinement.py opens the PRD gate through the event."""
    stack = build_stack(tmp_path)
    revision = stack.store.get_workflow(WORKFLOW_ID).revision
    card = WorkCard(
        id="card-prd", workflow_id=WORKFLOW_ID, kind=CardKind.PRD.value,
        title="PRD", state="done", attempt_count=1,
    )
    stack.store.create_card(card)

    route_prd_result(
        "<PRD>Build it.</PRD>", card, stack.gates, stack.artifacts
    )

    _assert_one_opening(stack.store, CardKind.PRD_GATE, revision)


def test_the_cab1_call_site(tmp_path: Path) -> None:
    """Ensure answering the strategic interview opens CAB-1 through the
    event (gates.py)."""
    stack = build_stack(tmp_path)
    interview = open_gate(
        stack, CardKind.STRATEGIC_INTERVIEW_GATE, None, "approve"
    )
    revision = stack.store.get_workflow(WORKFLOW_ID).revision

    stack.gates.resolve(interview.id, "approved")

    cab1 = [
        e for e in _opened(stack.store)
        if stack.store.get_card(e.card_id).kind == CardKind.CAB1_GATE.value
    ]
    assert len(cab1) == _ONE_EVENT
    assert stack.store.get_workflow(WORKFLOW_ID).revision > revision


def test_the_cab2_call_site(tmp_path: Path) -> None:
    """Ensure estimation.py opens CAB-2 through the event."""
    services, estimation = _estimation_setup(tmp_path)
    revision = services.store.get_workflow("wf-1").revision

    route_estimation_result(
        _estimates(_CODING, _MANUAL), estimation, services
    )

    (event,) = [
        e for e in services.store.list_events("wf-1")
        if e.event_type == "gate.opened"
    ]
    assert json.loads(event.payload) == {
        "gate_kind": CardKind.DECOMPOSITION_GATE.value
    }
    assert services.store.get_workflow("wf-1").revision > revision


def test_the_refinement_call_site(tmp_path: Path) -> None:
    """Ensure question_review.py opens each interview gate through the
    event."""
    services, store, _gates, artifacts = _interview(tmp_path)
    _drafted(
        store, artifacts, "pm",
        {"prompt": "Which format?", "options": ["CSV", "JSON"]},
    )
    member = store.get_card("ref-pm")

    after_draft(member, services)

    opened = [
        e for e in store.list_events("wf-1") if e.event_type == "gate.opened"
    ]
    assert len(opened) == _ONE_EVENT
    assert store.get_card(opened[0].card_id).kind == (
        CardKind.REFINEMENT_GATE.value
    )

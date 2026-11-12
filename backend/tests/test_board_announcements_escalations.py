"""What kestrel says on the ticket about a problem the verifier could not
settle (feature 046's announcements, applied to escalation gates)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.models_board import CardKind, WorkCard
from tests.announcement_support import (
    CHANGE_OWNER,
    REPORTER,
    WORKFLOW_ID,
    build_stack,
    open_gate,
    ticket,
)
from tests.test_board_announcements import _announced, _the_one


@pytest.mark.asyncio
async def test_an_escalation_asks_the_reporter_and_says_how_to_answer(
    tmp_path: Path,
) -> None:
    """Ensure the problem reaches the person who can settle it."""
    stack = build_stack(tmp_path)
    open_gate(
        stack, CardKind.ESCALATION_GATE, None, "resolve_escalation"
    )

    comment = (await _announced(stack))[0]

    assert "escalation_gate" in comment.plain_text()
    assert "accept the work" in comment.plain_text()
    assert comment.mentions() == frozenset({REPORTER.account_id})


@pytest.mark.asyncio
async def test_the_sweep_says_what_nothing_else_prompted(
    tmp_path: Path,
) -> None:
    """Ensure an unannounced gate is announced with no further board
    change to prompt it."""
    stack = build_stack(tmp_path)
    open_gate(
        stack, CardKind.ESCALATION_GATE, None, "resolve_escalation"
    )

    sweep = asyncio.create_task(stack.service.run_forever(0.01))
    await asyncio.sleep(0.2)
    sweep.cancel()

    assert len(stack.source.comments()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("within", "phrase"), [(True, "no new approval"), (False, "CAB")],
)
async def test_the_ticket_says_how_a_clarification_was_judged(
    tmp_path: Path, within: bool, phrase: str,
) -> None:
    """Ensure the reporter learns which path the clarification took."""
    stack = build_stack(tmp_path)

    await stack.service.clarification_judged(WORKFLOW_ID, "card-1", within)

    assert phrase in stack.source.comments()[0].plain_text()


@pytest.mark.asyncio
async def test_a_policy_risk_asks_the_change_owner_and_not_the_reporter(
    tmp_path: Path,
) -> None:
    """Ensure a flagged risk reaches the person who may accept it."""
    stack = build_stack(tmp_path)
    open_gate(stack, CardKind.POLICY_RISK_GATE, None, "resolve_policy_risk")

    comment = _the_one(await _announced(stack))

    assert "policy risk" in comment.plain_text()
    assert comment.mentions() == frozenset({CHANGE_OWNER.account_id})


@pytest.mark.asyncio
async def test_a_policy_risk_without_a_change_owner_is_decided_in_kestrel(
    tmp_path: Path,
) -> None:
    """Ensure the risk is not handed to the reporter by default."""
    stack = build_stack(tmp_path, source=ticket(change_owner=None))
    open_gate(stack, CardKind.POLICY_RISK_GATE, None, "resolve_policy_risk")

    comment = _the_one(await _announced(stack))

    assert "No change owner is set" in comment.plain_text()
    assert "Open the request in kestrel" in comment.plain_text()
    assert comment.mentions() == frozenset()


@pytest.mark.asyncio
async def test_a_handed_back_task_asks_the_change_owner_why_work_stopped(
    tmp_path: Path,
) -> None:
    """Ensure the escalation for a work item given back to a person says
    so, not that the verifier flagged a risk (#99)."""
    stack = build_stack(tmp_path)
    head = WorkCard(
        id="card-head", workflow_id=WORKFLOW_ID, kind="implementation",
        title="Add the table", state="claimed", task_node_id="t1",
    )
    stack.store.create_card(head)
    stack.gates.open_gate(WorkCard(
        id="card-gate", workflow_id=WORKFLOW_ID,
        kind=CardKind.POLICY_RISK_GATE.value,
        title="Work item DEV-1 was given back: Add the table",
        state="awaiting_human", source_card_id=head.id,
    ), "resolve_policy_risk")

    comment = _the_one(await _announced(stack))

    assert "given back to a person" in comment.plain_text()
    assert "will not deliver part" in comment.plain_text()
    assert "policy risk" not in comment.plain_text()
    assert comment.mentions() == frozenset({CHANGE_OWNER.account_id})

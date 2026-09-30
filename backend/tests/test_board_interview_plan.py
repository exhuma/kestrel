"""The coordinator decides who is interviewed (feature 038)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models_board import WorkCard
from app.services.board.dispatch_extras import interview_of
from app.services.board.interview_batch import open_plan
from app.services.board.interview_plan import (
    PlanError,
    interviewers,
    parse_plan,
    plan_context,
    route_plan_result,
)
from tests.interview_support import interview_stack


def _plan_reply(*ids: str) -> str:
    entries = [{"specialist": sid, "reason": "why"} for sid in ids]
    body = json.dumps({"interviewers": entries})
    return f"<INTERVIEWERS>{body}</INTERVIEWERS>"


def _accepted_plan(store) -> WorkCard:
    """A plan card whose result was accepted, as dispatch leaves it."""
    plan = WorkCard(
        id="plan-1", workflow_id="wf-1", kind="interview_plan",
        title="Plan interview round 1", state="done",
        eligible_roles=("coordinator",),
    )
    store.create_card(plan)
    return plan


def _kinds(store) -> list[str]:
    return [c.kind for c in store.list_cards("wf-1")]


def test_a_plan_names_specialists_in_order() -> None:
    assert parse_plan(_plan_reply("pm", "dba")) == ["pm", "dba"]


@pytest.mark.parametrize(
    "reply",
    ["no block", "<INTERVIEWERS>[]</INTERVIEWERS>",
     '<INTERVIEWERS>{"interviewers": "pm"}</INTERVIEWERS>'],
    ids=["missing", "not-an-object", "not-a-list"],
)
def test_an_unreadable_plan_is_refused(reply: str) -> None:
    with pytest.raises(PlanError):
        parse_plan(reply)


def test_only_specialists_that_can_interview_are_offered(
    tmp_path: Path,
) -> None:
    services, *_rest = interview_stack(tmp_path)

    assert interviewers(services.roster) == ["dba", "infosec", "pm"]


def test_the_plan_names_each_specialists_expertise_and_rounds(
    tmp_path: Path,
) -> None:
    services, store, _gates, _artifacts = interview_stack(tmp_path)
    plan = open_plan(store, "wf-1")

    context = plan_context(plan, interview_of(services))

    assert "- dba — DBA: dba expertise — 0 of 1" in context
    assert "first round: name at least one" in context


def test_a_plan_starts_a_batch_of_valid_interviewers(tmp_path: Path) -> None:
    """Ensure unknown, non-interviewing and repeated ids are ignored."""
    services, store, _gates, _artifacts = interview_stack(tmp_path)
    plan = _accepted_plan(store)

    route_plan_result(
        _plan_reply("dba", "coordinator", "nobody", "dba", "pm"), plan,
        interview_of(services),
    )

    batch = [c for c in store.list_cards("wf-1") if c.kind == "refinement"]
    assert [c.eligible_roles for c in batch] == [("dba",), ("pm",)]
    assert all(
        (c.id, plan.id) in {
            (r.card_id, r.depends_on_card_id)
            for r in store.list_relations("wf-1")
        }
        for c in batch
    )
    assert store.get_card(plan.id).state == "done"


def test_a_specialist_with_no_rounds_left_is_not_asked_again(
    tmp_path: Path,
) -> None:
    services, store, _gates, _artifacts = interview_stack(tmp_path)
    store.create_card(WorkCard(
        id="old", workflow_id="wf-1", kind="refinement",
        title="dba interview questions", state="done",
        eligible_roles=("dba",),
    ))
    plan = _accepted_plan(store)

    route_plan_result(_plan_reply("dba"), plan, interview_of(services))

    assert "prd" in _kinds(store)  # nobody valid left: interview complete


def test_an_empty_first_plan_fails_closed(tmp_path: Path) -> None:
    services, store, _gates, _artifacts = interview_stack(tmp_path)
    plan = _accepted_plan(store)

    route_plan_result(_plan_reply(), plan, interview_of(services))

    assert "coordinator_review" in _kinds(store)
    assert "prd" not in _kinds(store)


def test_an_unreadable_plan_fails_closed(tmp_path: Path) -> None:
    services, store, _gates, _artifacts = interview_stack(tmp_path)
    plan = _accepted_plan(store)

    route_plan_result("I think pm", plan, interview_of(services))

    assert "coordinator_review" in _kinds(store)

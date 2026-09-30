"""No question is asked twice (feature 038)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models_board import CardRelation, WorkCard
from app.services.board.artifacts import ArtifactDraft
from app.services.board.dispatch_extras import interview_of
from app.services.board.question_review import (
    after_draft,
    answered_elsewhere,
    parse_drops,
    route_review_result,
)
from tests.interview_support import interview_stack

_NEW = {"pm-1", "pm-2", "dba-1"}


def _reply(*drops: tuple[str, str]) -> str:
    body = [{"question": q, "duplicate_of": o} for q, o in drops]
    text = json.dumps({"drop": body})
    return f"<QUESTION_REVIEW>{text}</QUESTION_REVIEW>"


def test_a_duplicate_is_dropped_in_favour_of_the_kept_question() -> None:
    assert parse_drops(_reply(("dba-1", "pm-1")), _NEW, set()) == {
        "dba-1": "pm-1"
    }


def test_a_question_can_repeat_one_asked_earlier() -> None:
    drops = parse_drops(_reply(("pm-2", "earlier-1")), _NEW, {"earlier-1"})

    assert drops == {"pm-2": "earlier-1"}


@pytest.mark.parametrize(
    "reply",
    [
        _reply(("xx-1", "pm-1")),                     # unknown question
        _reply(("pm-1", "nowhere")),                   # unknown original
        _reply(("pm-1", "pm-1")),                      # itself
        _reply(("dba-1", "pm-1"), ("dba-1", "pm-2")),  # dropped twice
        _reply(("dba-1", "pm-1"), ("pm-1", "pm-2")),   # a chain
        "no block at all",
        '<QUESTION_REVIEW>{"drop": "pm-1"}</QUESTION_REVIEW>',
    ],
    ids=["unknown", "no-original", "self", "twice", "chain", "missing",
         "not-a-list"],
)
def test_a_reply_breaking_a_rule_drops_nothing(reply: str) -> None:
    assert parse_drops(reply, _NEW, set()) is None


def _drafted(store, artifacts, persona: str, *prompts: str) -> WorkCard:
    """A batch member whose accepted draft holds *prompts*."""
    card = WorkCard(
        id=f"ref-{persona}", workflow_id="wf-1", kind="refinement",
        title=f"{persona} interview questions (round 1)", state="done",
        eligible_roles=(persona,),
    )
    store.create_card(card)
    store.add_relation(CardRelation(card.id, "plan-1"))
    artifacts.store_reference_artifact(ArtifactDraft(
        producer_card_id=card.id, logical_name="questions", revision=0,
        content=json.dumps({"questions": list(prompts)}),
        trust="agent_output",
    ))
    return card


def _stack(tmp_path: Path):
    services, store, gates, artifacts = interview_stack(tmp_path)
    store.create_card(WorkCard(
        id="plan-1", workflow_id="wf-1", kind="interview_plan",
        title="Plan interview round 1", state="done",
        eligible_roles=("coordinator",),
    ))
    return interview_of(services), store, gates, artifacts


def _review(store) -> WorkCard:
    """The batch's review card, its result accepted — as dispatch leaves
    it before routing."""
    (review,) = [
        c for c in store.list_cards("wf-1") if c.kind == "question_review"
    ]
    store.set_card_state(review.id, "done")
    return store.get_card(review.id)


def _asked(store, gates, artifacts) -> dict[str, list]:
    cards = store.list_cards("wf-1")
    personas = gates.interview_personas(cards)
    return {
        personas[c.id]: json.loads(artifacts.read_content(
            gates.get_gate(c.id).target_artifact_id
        ))["questions"]
        for c in cards if c.kind == "refinement_gate"
    }


def test_nothing_is_reviewed_while_someone_still_drafts(
    tmp_path: Path,
) -> None:
    interview, store, _gates, artifacts = _stack(tmp_path)
    pm = _drafted(store, artifacts, "pm", "When?")
    store.create_card(WorkCard(
        id="ref-dba", workflow_id="wf-1", kind="refinement",
        title="dba interview questions", state="claimed",
        eligible_roles=("dba",),
    ))
    store.add_relation(CardRelation("ref-dba", "plan-1"))

    after_draft(pm, interview)

    assert "question_review" not in [c.kind for c in store.list_cards("wf-1")]


def test_duplicates_are_asked_once(tmp_path: Path) -> None:
    interview, store, gates, artifacts = _stack(tmp_path)
    _drafted(store, artifacts, "pm", "When?", "Budget?")
    dba = _drafted(store, artifacts, "dba", "When?", "Where stored?")
    after_draft(dba, interview)

    route_review_result(
        _reply(("dba-1", "pm-1")), _review(store), interview
    )

    assert _asked(store, gates, artifacts) == {
        "pm": ["When?", "Budget?"], "dba": ["Where stored?"],
    }


def test_an_unusable_review_asks_everything_unchanged(tmp_path: Path) -> None:
    """Ensure no question is ever lost to a bad review (FR-004)."""
    interview, store, gates, artifacts = _stack(tmp_path)
    _drafted(store, artifacts, "pm", "When?")
    dba = _drafted(store, artifacts, "dba", "When?")
    after_draft(dba, interview)

    route_review_result(
        _reply(("dba-1", "dba-1")), _review(store), interview
    )

    assert _asked(store, gates, artifacts) == {
        "pm": ["When?"], "dba": ["When?"],
    }
    assert store.list_events("wf-1")[-1].event_type == (
        "question_review.ignored"
    )


def test_a_set_asked_entirely_elsewhere_opens_no_gate(tmp_path: Path) -> None:
    interview, store, gates, artifacts = _stack(tmp_path)
    _drafted(store, artifacts, "pm", "When?")
    dba = _drafted(store, artifacts, "dba", "When?")
    after_draft(dba, interview)

    route_review_result(_reply(("dba-1", "pm-1")), _review(store), interview)

    assert _asked(store, gates, artifacts) == {"pm": ["When?"]}


def test_the_answer_given_elsewhere_reaches_the_asker(tmp_path: Path) -> None:
    """FR-006: dba's next round learns what pm's human answered."""
    interview, store, gates, artifacts = _stack(tmp_path)
    _drafted(store, artifacts, "pm", "When?")
    dba = _drafted(store, artifacts, "dba", "When is it due?")
    after_draft(dba, interview)
    route_review_result(_reply(("dba-1", "pm-1")), _review(store), interview)
    (gate,) = [
        c for c in store.list_cards("wf-1") if c.kind == "refinement_gate"
    ]

    gates.resolve(gate.id, "approved", answer="Q: When?\nA: Friday.")

    assert answered_elsewhere(dba, interview) == (
        "Your questions that another profile answered instead:\n"
        "- When is it due? — asked of pm as “When?”: Friday."
    )


def test_a_lone_first_set_opens_its_gate_without_a_review(
    tmp_path: Path,
) -> None:
    interview, store, gates, artifacts = _stack(tmp_path)
    pm = _drafted(store, artifacts, "pm", "When?")

    after_draft(pm, interview)

    assert _asked(store, gates, artifacts) == {"pm": ["When?"]}
    assert "question_review" not in [c.kind for c in store.list_cards("wf-1")]


def test_an_interview_begun_before_038_continues_with_a_plan(
    tmp_path: Path,
) -> None:
    """Ensure a pre-038 interview's last answer hands over to the
    coordinator's plan instead of stalling."""
    _services, store, gates, artifacts = interview_stack(tmp_path)
    card = WorkCard(
        id="ref-uiux", workflow_id="wf-1", kind="refinement",
        title="uiux interview questions", state="done",
        eligible_roles=("uiux",),
    )
    store.create_card(card)
    target = artifacts.store_reference_artifact(ArtifactDraft(
        producer_card_id=card.id, logical_name="questions", revision=0,
        content=json.dumps({"questions": ["Mobile?"]}), trust="agent_output",
    ))
    gate = gates.create_gate(
        "wf-1", kind="refinement_gate", title="uiux interview (1 question)",
        requested_decision="answer", target_artifact_id=target.id,
    )

    gates.resolve(gate.id, "approved", answer="Q: Mobile?\nA: Yes.")

    assert "interview_plan" in [c.kind for c in store.list_cards("wf-1")]

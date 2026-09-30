"""A request's activity, derived purely (feature 033)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.models_board import WorkCard
from app.models_board_records import BoardEventRecord
from app.services.board.activity import ActivityInputs, activity_of
from app.services.board.intake import SCREENING_TITLE
from app.services.board.live_activity import LiveTurn

_T0 = datetime(2026, 9, 29, 10, 0)
_LABELS = {"pm": "Project Manager"}


def _card(
    card_id: str, state: str, *, kind: str = "understanding",
    roles: tuple[str, ...] = ("pm",), title: str | None = None,
) -> WorkCard:
    return WorkCard(
        id=card_id, workflow_id="wf-1", kind=kind, title=title or card_id,
        state=state, eligible_roles=roles,
    )


def _event(
    event_type: str, card_id: str | None = None, detail: str | None = None
) -> BoardEventRecord:
    payload = json.dumps({"detail": detail}) if detail else "{}"
    return BoardEventRecord(
        workflow_id="wf-1", event_type=event_type, card_id=card_id,
        payload=payload, created_at=_T0,
    )


def _of(
    cards: list[WorkCard],
    events: list[BoardEventRecord] | None = None,
    *,
    live: LiveTurn | None = None,
    outcome: str = "in_progress",
):
    return activity_of(
        ActivityInputs(cards, events or [], live, outcome, _LABELS)
    )


def test_live_work_is_working_whatever_the_cards_say() -> None:
    live = LiveTurn("Project Manager", "Restate", datetime.now(timezone.utc))

    activity = _of([_card("c", "failed")], live=live)

    assert (activity.state, activity.actor, activity.subject) == (
        "working", "Project Manager", "Restate",
    )


def test_a_failed_card_is_a_problem() -> None:
    activity = _of([_card("Restate", "failed"), _card("x", "ready")])

    assert (activity.state, activity.subject) == ("problem", "Restate")


def test_a_failed_turn_is_a_problem_until_progress() -> None:
    """Ensure a recorded failure shows, and clears on the next change."""
    failed = _event(
        "coordinator.turn_failed", detail="the coordinator's turn timed out"
    )
    cards = [_card("c", "ready")]

    problem = _of(cards, [failed])
    assert (problem.state, problem.actor, problem.detail) == (
        "problem", "coordinator", "the coordinator's turn timed out",
    )
    assert problem.since == _T0.replace(tzinfo=timezone.utc)

    later = _of(cards, [failed, _event("card.result_accepted", "c")])
    assert later.state == "queued"


def test_an_operator_decision_is_waiting_for_you() -> None:
    activity = _of([
        _card("Confirm", "awaiting_human", kind="understanding_gate", roles=()),
        _card("x", "ready"),
    ])

    assert (activity.state, activity.subject) == ("waiting", "Confirm")


def test_unclaimed_ready_work_is_queued_for_its_role() -> None:
    activity = _of(
        [_card("Restate", "ready")],
        [_event("card.dependency_met", "Restate")],
    )

    assert (activity.state, activity.actor, activity.subject) == (
        "queued", "Project Manager", "Restate",
    )
    assert activity.since == _T0.replace(tzinfo=timezone.utc)


def test_a_finished_request_is_done() -> None:
    assert _of([_card("c", "done")], outcome="done").state == "done"


def test_a_stopped_request_is_cancelled_never_done() -> None:
    """Feature 040: terminal is not done."""
    activity = _of([_card("c", "cancelled")], outcome="cancelled")

    assert activity.state == "cancelled"


@pytest.mark.parametrize(
    ("cards", "reason"),
    [
        (
            [_card("s", "claimed", kind="security_review", roles=(),
                   title=SCREENING_TITLE)],
            "interrupted_screening",
        ),
        ([_card("Restate", "claimed")], "interrupted_claim"),
        ([_card("c", "waiting_dependency")], "nothing_ready"),
    ],
    ids=["screening", "claim", "nothing"],
)
def test_nothing_moving_is_stalled_never_working(
    cards: list[WorkCard], reason: str
) -> None:
    """Ensure stored state alone never reads as "working" (SC-002)."""
    activity = _of(cards)

    assert (activity.state, activity.reason) == ("stalled", reason)


def test_a_failed_turn_never_hides_a_decision_waiting_for_you() -> None:
    """Ensure a retried coordinator failure does not mask a gate the
    operator must answer; a failed card still comes first."""
    failed_turn = _event(
        "coordinator.turn_failed", detail="the coordinator's turn timed out"
    )
    gate = _card(
        "Confirm", "awaiting_human", kind="understanding_gate", roles=()
    )

    assert _of([gate], [failed_turn]).state == "waiting"
    assert _of([gate, _card("Build", "failed")], [failed_turn]).subject == (
        "Build"
    )

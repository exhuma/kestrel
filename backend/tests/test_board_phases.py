"""Tests for the derived phase/stage projection (GitHub #55).

A pure, display-only label over card kinds — no store, no writes. See
``app.services.board.phases`` for why this must never become a driver.
"""
from __future__ import annotations

from app.models_board import WorkCard
from app.services.board.phases import (
    current_phase,
    outcome_of,
    phase_statuses,
    stage_of,
)


def _card(
    card_id: str, kind: str, state: str = "ready",
    task_node_id: str | None = None,
) -> WorkCard:
    return WorkCard(
        id=card_id,
        workflow_id="wf-1",
        kind=kind,
        title="a card",
        state=state,
        task_node_id=task_node_id,
    )


def _wf_36ca7a1a(pm_state: str) -> list[WorkCard]:
    """The operator's run (handover, 2026-09-30): intake, understanding
    and CAB-1 done, then a first interview batch whose pm card failed."""
    return [
        _card("s", "security_review", state="done"),
        _card("u", "understanding", state="done"),
        _card("ug", "understanding_gate", state="done"),
        _card("si", "strategic_interview", state="done"),
        _card("sg", "strategic_interview_gate", state="done"),
        _card("c1", "cab1_gate", state="done"),
        _card("ip", "interview_plan", state="done"),
        _card("dev", "refinement", state="done"),
        _card("ux", "refinement", state="done"),
        _card("pm", "refinement", state=pm_state),
    ]


class TestOutcome:
    """A request is done only when it reached its end (feature 040)."""

    def test_a_failed_card_makes_the_request_failed_not_done(self) -> None:
        """Reproduces wf-36ca7a1a: every other card terminal, one failed."""
        cards = _wf_36ca7a1a("failed")

        assert outcome_of(cards) == "failed"
        assert current_phase(cards) == "Pre-assessment"
        assert stage_of(current_phase(cards)) == "Discovery"

    def test_a_failure_wins_over_open_work(self) -> None:
        cards = [
            _card("a", "implementation", state="claimed"),
            _card("b", "verification", state="failed"),
        ]
        assert outcome_of(cards) == "failed"

    def test_stopping_before_the_end_is_cancelled_not_done(self) -> None:
        """wf-36ca7a1a after the coordinator cancelled the failed card."""
        cards = _wf_36ca7a1a("cancelled")

        assert outcome_of(cards) == "cancelled"
        assert current_phase(cards) == "cancelled"
        assert stage_of("cancelled") == "Cancelled"

    def test_a_done_delivery_is_done(self) -> None:
        cards = [
            _card("g", "decomposition_gate", state="done"),
            _card("i", "implementation", state="done", task_node_id="t1"),
            _card("d", "delivery", state="done"),
            _card("r", "prd_gate", state="cancelled"),  # an earlier redraft
        ]
        assert outcome_of(cards) == "done"
        assert current_phase(cards) == "done"

    def test_manual_only_work_is_done_once_every_task_is(self) -> None:
        cards = [
            _card("g", "decomposition_gate", state="done"),
            _card("m", "manual_task", state="done", task_node_id="t1"),
        ]
        assert outcome_of(cards) == "done"

    def test_approved_coding_work_without_a_delivery_is_not_done(
        self,
    ) -> None:
        cards = [
            _card("g", "decomposition_gate", state="done"),
            _card("i", "implementation", state="cancelled", task_node_id="t1"),
        ]
        assert outcome_of(cards) == "cancelled"

    def test_an_empty_board_is_in_progress(self) -> None:
        assert outcome_of([]) == "in_progress"
        assert current_phase([]) == "Intake"


class TestCurrentPhase:
    """The lowest-ordinal phase with a non-terminal card wins."""

    def test_all_terminal_cards_are_not_done_by_themselves(self) -> None:
        """The old rule (feature 040): terminal is not the same as done."""
        cards = [
            _card("a", "security_review", state="done"),
            _card("b", "prd_gate", state="cancelled"),
        ]
        assert current_phase(cards) == "cancelled"

    def test_an_open_manual_task_keeps_the_request_unfinished(
        self,
    ) -> None:
        """Ensure a workflow is not done because the code is (feature
        031, SC-004)."""
        cards = [
            _card("d", "delivery", state="done"),
            _card("m", "manual_task", state="awaiting_human"),
        ]
        assert current_phase(cards) == "Build"

    def test_single_outstanding_card_reports_its_phase(self) -> None:
        cards = [_card("a", "prd", state="ready")]
        assert current_phase(cards) == "PRD"

    def test_parallel_cards_spanning_two_phases_the_lower_ordinal_wins(
        self,
    ) -> None:
        cards = [
            _card("a", "analysis", state="ready"),  # Technical analysis
            _card("b", "understanding_gate", state="awaiting_human"),
        ]
        assert current_phase(cards) == "Understanding"

    def test_terminal_cards_do_not_count_toward_their_phase(self) -> None:
        cards = [
            _card("a", "understanding_gate", state="done"),
            _card("b", "prd", state="ready"),
        ]
        assert current_phase(cards) == "PRD"

    def test_unknown_card_kind_is_not_counted_and_does_not_raise(
        self,
    ) -> None:
        cards = [_card("a", "some_future_kind", state="ready")]
        assert current_phase(cards) == "Intake"  # open work: not done

    def test_unknown_card_kind_alongside_a_known_one_is_ignored(
        self,
    ) -> None:
        cards = [
            _card("a", "some_future_kind", state="ready"),
            _card("b", "prd_gate", state="awaiting_human"),
        ]
        assert current_phase(cards) == "PRD sign-off"


class TestStageOf:
    """Every phase maps to its grouping stage."""

    def test_intake_and_understanding_share_a_stage(self) -> None:
        assert stage_of("Intake") == "Intake & alignment"
        assert stage_of("Understanding") == "Intake & alignment"

    def test_cab1_and_pre_assessment_share_discovery(self) -> None:
        assert stage_of("CAB-1 - strategic fit") == "Discovery"
        assert stage_of("Pre-assessment") == "Discovery"

    def test_build_and_delivery_share_build_and_deliver(self) -> None:
        assert stage_of("Build") == "Build & deliver"
        assert stage_of("Delivery") == "Build & deliver"

    def test_done_has_its_own_stage(self) -> None:
        assert stage_of("done") == "Done"


class TestPhaseStatuses:
    """Every spine step has a status, finished or not (feature 034)."""

    def test_a_finished_request_marks_every_step(self) -> None:
        """Ensure no step is left blank: reached steps are done, the
        rest skipped."""
        cards = [
            _card("s", "security_review", state="done"),
            _card("u", "understanding_gate", state="done"),
            _card("p", "prd_gate", state="cancelled"),
            _card("d", "delivery", state="done"),
        ]
        statuses = dict(phase_statuses(cards))

        assert statuses["Intake"] == "done"
        assert statuses["Understanding"] == "done"
        assert statuses["PRD sign-off"] == "skipped"
        assert statuses["Delivery"] == "done"
        assert "upcoming" not in statuses.values()

    def test_a_failed_request_never_reads_as_a_finished_path(self) -> None:
        """Reproduces wf-36ca7a1a's spine: no later step is skipped."""
        statuses = dict(phase_statuses(_wf_36ca7a1a("failed")))

        assert statuses["Pre-assessment"] == "problem"
        later = ["PRD", "PRD sign-off", "Technical analysis",
                 "CAB-2 - go/no-go", "Build", "Delivery"]
        assert {statuses[p] for p in later} == {"upcoming"}

    def test_a_cancelled_request_says_where_it_stopped(self) -> None:
        statuses = dict(phase_statuses(_wf_36ca7a1a("cancelled")))

        assert statuses["CAB-1 - strategic fit"] == "done"
        assert statuses["Pre-assessment"] == "cancelled"
        assert statuses["PRD"] == "upcoming"
        assert "skipped" not in statuses.values()

    def test_a_request_in_progress(self) -> None:
        cards = [
            _card("s", "security_review", state="done"),
            _card("u", "understanding_gate", state="awaiting_human"),
        ]
        statuses = dict(phase_statuses(cards))

        assert statuses["Intake"] == "done"
        assert statuses["Understanding"] == "waiting"
        assert statuses["CAB-1 - strategic fit"] == "upcoming"

    def test_work_under_way_and_a_failure(self) -> None:
        statuses = dict(phase_statuses([
            _card("i", "implementation", state="claimed"),
            _card("d", "delivery", state="failed"),
        ]))

        assert statuses["Build"] == "active"
        assert statuses["Delivery"] == "problem"
        assert statuses["PRD"] == "skipped"

"""Tests for the derived phase/stage projection (GitHub #55).

A pure, display-only label over card kinds — no store, no writes. See
``app.services.board.phases`` for why this must never become a driver.
"""
from __future__ import annotations

from app.models_board import WorkCard
from app.services.board.phases import current_phase, stage_of


def _card(card_id: str, kind: str, state: str = "ready") -> WorkCard:
    return WorkCard(
        id=card_id,
        workflow_id="wf-1",
        kind=kind,
        title="a card",
        state=state,
    )


class TestCurrentPhase:
    """The lowest-ordinal phase with a non-terminal card wins."""

    def test_empty_board_is_done(self) -> None:
        assert current_phase([]) == "done"

    def test_all_terminal_cards_is_done(self) -> None:
        cards = [
            _card("a", "security_review", state="done"),
            _card("b", "prd_gate", state="cancelled"),
        ]
        assert current_phase(cards) == "done"

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
        assert current_phase(cards) == "done"

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

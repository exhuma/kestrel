"""Pure state/dependency policy tests for the board domain (feature 026).

Exercises ``app.models_board`` and ``app.services.board.policy``
against ``specs/026-autonomous-work-board/data-model.md``: card-state
transition legality and dependency/cycle rejection. No persistence layer
is involved — these are pure-function tests.
"""
from __future__ import annotations

import pytest

from app.models_board import (
    CardRelation,
    CardState,
    RelationKind,
)
from app.services.board.policy import (
    CycleError,
    dependencies_met,
    is_valid_transition,
    validate_new_relation,
)


class TestStateTransitions:
    """Card-state transitions follow the data-model's allowed-origins."""

    def test_ready_to_claimed_is_valid(self) -> None:
        assert is_valid_transition(CardState.READY, CardState.CLAIMED)

    def test_claimed_to_review_is_valid(self) -> None:
        assert is_valid_transition(CardState.CLAIMED, CardState.REVIEW)

    def test_review_to_done_is_valid(self) -> None:
        assert is_valid_transition(CardState.REVIEW, CardState.DONE)

    def test_ready_to_waiting_dependency_is_valid(self) -> None:
        assert is_valid_transition(
            CardState.READY, CardState.WAITING_DEPENDENCY
        )

    def test_waiting_dependency_to_ready_is_valid(self) -> None:
        assert is_valid_transition(
            CardState.WAITING_DEPENDENCY, CardState.READY
        )

    def test_ready_to_awaiting_human_is_valid(self) -> None:
        assert is_valid_transition(CardState.READY, CardState.AWAITING_HUMAN)

    def test_claimed_cannot_skip_directly_to_done(self) -> None:
        assert not is_valid_transition(CardState.CLAIMED, CardState.DONE)

    def test_ready_cannot_transition_to_quarantined(self) -> None:
        """Quarantine is entered only at input intake, never by transition."""
        assert not is_valid_transition(
            CardState.READY, CardState.QUARANTINED
        )

    @pytest.mark.parametrize(
        "terminal", [CardState.DONE, CardState.FAILED, CardState.CANCELLED]
    )
    def test_terminal_states_accept_no_further_transition(
        self, terminal: CardState
    ) -> None:
        assert not is_valid_transition(terminal, CardState.READY)
        assert not is_valid_transition(terminal, CardState.CLAIMED)

    @pytest.mark.parametrize(
        "origin",
        [
            CardState.READY,
            CardState.CLAIMED,
            CardState.WAITING_DEPENDENCY,
            CardState.AWAITING_HUMAN,
            CardState.REVIEW,
        ],
    )
    def test_non_terminal_states_can_be_cancelled(
        self, origin: CardState
    ) -> None:
        assert is_valid_transition(origin, CardState.CANCELLED)


class TestCycleRejection:
    """Card dependency graphs must stay acyclic."""

    def test_self_dependency_rejected(self) -> None:
        with pytest.raises(CycleError):
            validate_new_relation(
                (), CardRelation("a", "a", RelationKind.DEPENDENCY)
            )

    def test_direct_cycle_rejected(self) -> None:
        existing = (CardRelation("a", "b", RelationKind.DEPENDENCY),)
        with pytest.raises(CycleError):
            validate_new_relation(
                existing, CardRelation("b", "a", RelationKind.DEPENDENCY)
            )

    def test_longer_cycle_rejected(self) -> None:
        existing = (
            CardRelation("a", "b", RelationKind.DEPENDENCY),
            CardRelation("b", "c", RelationKind.DEPENDENCY),
        )
        with pytest.raises(CycleError):
            validate_new_relation(
                existing, CardRelation("c", "a", RelationKind.DEPENDENCY)
            )

    def test_valid_dag_accepted(self) -> None:
        existing = (CardRelation("a", "b", RelationKind.DEPENDENCY),)
        # Does not raise.
        validate_new_relation(
            existing, CardRelation("a", "c", RelationKind.DEPENDENCY)
        )

    def test_diamond_dependency_accepted(self) -> None:
        existing = (
            CardRelation("d", "b", RelationKind.DEPENDENCY),
            CardRelation("d", "c", RelationKind.DEPENDENCY),
            CardRelation("b", "a", RelationKind.DEPENDENCY),
        )
        # c also depending on a is a diamond, not a cycle.
        validate_new_relation(
            existing, CardRelation("c", "a", RelationKind.DEPENDENCY)
        )


class TestDependenciesMet:
    """Readiness derives from upstream dependency completion."""

    def test_true_when_no_dependencies(self) -> None:
        assert dependencies_met("card", (), {})

    def test_true_when_all_dependencies_done(self) -> None:
        relations = (CardRelation("card", "up1", RelationKind.DEPENDENCY),)
        states = {"up1": CardState.DONE}
        assert dependencies_met("card", relations, states)

    def test_false_when_a_dependency_is_incomplete(self) -> None:
        relations = (
            CardRelation("card", "up1", RelationKind.DEPENDENCY),
            CardRelation("card", "up2", RelationKind.DEPENDENCY),
        )
        states = {"up1": CardState.DONE, "up2": CardState.CLAIMED}
        assert not dependencies_met("card", relations, states)

    def test_ignores_relations_for_other_cards(self) -> None:
        relations = (
            CardRelation("other", "up1", RelationKind.DEPENDENCY),
        )
        states = {"up1": CardState.CLAIMED}
        assert dependencies_met("card", relations, states)

    def test_ignores_non_dependency_relations(self) -> None:
        relations = (
            CardRelation("card", "peer", RelationKind.RECONCILIATION),
        )
        states = {"peer": CardState.CLAIMED}
        assert dependencies_met("card", relations, states)

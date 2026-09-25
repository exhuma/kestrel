"""Coordinator action-schema, validation, replay, and forbidden-action
tests (feature 026, T028).

The coordinator only *proposes* actions; ``CoordinatorService`` is the
policy-delegated authority that validates and applies them (FR-005),
recording every proposal — accepted or rejected — in the ledger before
(and regardless of) whether it's applied (FR-006).
"""
from __future__ import annotations

from pathlib import Path

from app.models_board import WorkCard, Workflow
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_store import BoardStore
from app.services.board.coordinator import (
    CoordinatorService,
    CreateCardAction,
    CreateReconciliationCardAction,
    TransitionCardAction,
    parse_coordinator_actions,
)
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory


def _coordinator(
    tmp_path: Path, *, decomposition_required: bool = False,
    prd_gate_required: bool = False, skip_decomposition: bool = False,
) -> tuple[CoordinatorService, BoardStore]:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    coordinator_store = BoardCoordinatorStore(factory)
    board_service = BoardService(store)
    store.create_workflow(
        Workflow(
            id="wf-1",
            source="github-issue",
            task_ref="owner/repo#1",
            repo="owner/repo",
            base_branch="main",
            source_visibility="public",
            title="Add a thing",
            skip_decomposition=skip_decomposition,
        )
    )
    store.create_card(
        WorkCard(
            id="card-1",
            workflow_id="wf-1",
            kind="analysis",
            title="Investigate",
            state="ready",
        )
    )
    service = CoordinatorService(
        store, coordinator_store, board_service,
        decomposition_required=decomposition_required,
        prd_gate_required=prd_gate_required,
    )
    return service, store


class TestParseCoordinatorActions:
    """Parsing the coordinator's structured output block."""

    def test_parses_a_well_formed_action_list(self) -> None:
        text = (
            '<COORDINATOR_ACTIONS>{"actions": ['
            '{"type": "transition_card", "card_id": "card-1", '
            '"target_state": "cancelled"}'
            "]}</COORDINATOR_ACTIONS>"
        )
        actions = parse_coordinator_actions(text)
        assert actions == [
            TransitionCardAction(card_id="card-1", target_state="cancelled")
        ]

    def test_returns_none_when_tag_is_absent(self) -> None:
        assert parse_coordinator_actions("no block here") is None

    def test_returns_none_on_malformed_json(self) -> None:
        text = "<COORDINATOR_ACTIONS>{not json}</COORDINATOR_ACTIONS>"
        assert parse_coordinator_actions(text) is None

    def test_empty_action_list_is_valid(self) -> None:
        text = '<COORDINATOR_ACTIONS>{"actions": []}</COORDINATOR_ACTIONS>'
        assert parse_coordinator_actions(text) == []

    def test_unknown_action_type_is_dropped_not_fatal(self) -> None:
        text = (
            '<COORDINATOR_ACTIONS>{"actions": ['
            '{"type": "delete_everything"}, '
            '{"type": "transition_card", "card_id": "card-1", '
            '"target_state": "cancelled"}'
            "]}</COORDINATOR_ACTIONS>"
        )
        actions = parse_coordinator_actions(text)
        assert actions == [
            TransitionCardAction(card_id="card-1", target_state="cancelled")
        ]


class TestValidationAndApplication:
    """Every proposed action is policy-validated before it can mutate."""

    def test_valid_transition_is_accepted_and_applied(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path)
        records = coordinator.apply_actions(
            "wf-1",
            "card.done",
            [TransitionCardAction(card_id="card-1", target_state="cancelled")],
        )
        assert records[0].validation_decision == "accepted"
        assert records[0].applied is True
        assert store.get_card("card-1").state == "cancelled"

    def test_illegal_transition_is_rejected_and_not_applied(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path)
        records = coordinator.apply_actions(
            "wf-1",
            "card.done",
            [TransitionCardAction(card_id="card-1", target_state="done")],
        )
        assert records[0].validation_decision == "rejected"
        assert records[0].applied is False
        assert store.get_card("card-1").state == "ready"

    def test_transition_of_unknown_card_is_rejected(
        self, tmp_path: Path
    ) -> None:
        coordinator, _store = _coordinator(tmp_path)
        records = coordinator.apply_actions(
            "wf-1",
            "card.done",
            [TransitionCardAction(card_id="missing", target_state="cancelled")],
        )
        assert records[0].validation_decision == "rejected"
        assert records[0].applied is False

    def test_create_card_is_accepted_and_creates_a_ready_card(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path)
        records = coordinator.apply_actions(
            "wf-1",
            "task.ingested",
            [CreateCardAction(kind="analysis", title="Look into it")],
        )
        assert records[0].validation_decision == "accepted"
        cards = store.list_cards("wf-1")
        new_cards = [c for c in cards if c.title == "Look into it"]
        assert len(new_cards) == 1
        assert new_cards[0].state == "ready"

    def test_create_card_with_dependency_starts_waiting(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path)
        records = coordinator.apply_actions(
            "wf-1",
            "task.ingested",
            [
                CreateCardAction(
                    kind="analysis",
                    title="Depends on card-1",
                    depends_on=("card-1",),
                )
            ],
        )
        assert records[0].validation_decision == "accepted"
        new_card = next(
            c
            for c in store.list_cards("wf-1")
            if c.title == "Depends on card-1"
        )
        assert new_card.state == "waiting_dependency"

    def test_create_card_depending_on_unknown_card_is_rejected(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path)
        records = coordinator.apply_actions(
            "wf-1",
            "task.ingested",
            [
                CreateCardAction(
                    kind="analysis", title="x", depends_on=("missing",)
                )
            ],
        )
        assert records[0].validation_decision == "rejected"
        assert len(store.list_cards("wf-1")) == 1

    def test_create_card_with_unsupported_kind_is_rejected(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path)
        records = coordinator.apply_actions(
            "wf-1", "task.ingested", [CreateCardAction(kind="nope", title="x")]
        )
        assert records[0].validation_decision == "rejected"
        assert len(store.list_cards("wf-1")) == 1

    def test_reconciliation_card_links_the_conflicting_cards(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path)
        store.create_card(
            WorkCard(
                id="card-2",
                workflow_id="wf-1",
                kind="analysis",
                title="Second",
                state="review",
            )
        )
        records = coordinator.apply_actions(
            "wf-1",
            "card.conflict",
            [
                CreateReconciliationCardAction(
                    title="Resolve conflict",
                    conflicting_card_ids=("card-1", "card-2"),
                )
            ],
        )
        assert records[0].validation_decision == "accepted"
        relations = store.list_relations("wf-1")
        reconciliation_targets = {
            r.depends_on_card_id
            for r in relations
            if r.kind == "reconciliation"
        }
        assert reconciliation_targets == {"card-1", "card-2"}

    def test_reconciliation_needs_at_least_two_cards(
        self, tmp_path: Path
    ) -> None:
        coordinator, _store = _coordinator(tmp_path)
        records = coordinator.apply_actions(
            "wf-1",
            "card.conflict",
            [
                CreateReconciliationCardAction(
                    title="x", conflicting_card_ids=("card-1",)
                )
            ],
        )
        assert records[0].validation_decision == "rejected"

    def test_multiple_actions_each_get_their_own_ledger_entry(
        self, tmp_path: Path
    ) -> None:
        coordinator, _store = _coordinator(tmp_path)
        records = coordinator.apply_actions(
            "wf-1",
            "task.ingested",
            [
                CreateCardAction(kind="analysis", title="a"),
                CreateCardAction(kind="analysis", title="b"),
            ],
        )
        first, second = records
        assert first.sequence != second.sequence


class TestReplay:
    """The same trigger is not reprocessed once already handled."""

    def test_second_call_with_the_same_trigger_is_a_no_op(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path)
        coordinator.apply_actions(
            "wf-1",
            "task.ingested",
            [CreateCardAction(kind="analysis", title="only once")],
        )
        coordinator.apply_actions(
            "wf-1",
            "task.ingested",
            [CreateCardAction(kind="analysis", title="only once")],
        )
        matching = [
            c for c in store.list_cards("wf-1") if c.title == "only once"
        ]
        assert len(matching) == 1

    def test_a_different_trigger_is_processed_independently(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path)
        coordinator.apply_actions(
            "wf-1",
            "trigger-a",
            [CreateCardAction(kind="analysis", title="from a")],
        )
        coordinator.apply_actions(
            "wf-1",
            "trigger-b",
            [CreateCardAction(kind="analysis", title="from b")],
        )
        titles = {c.title for c in store.list_cards("wf-1")}
        assert {"from a", "from b"} <= titles


class TestDecompositionEnforcement:
    """T068: with board_decomposition_required on, only analysis/
    decomposition/coordinator_review cards may be created until a
    decomposition_gate for this workflow reaches done."""

    def test_a_design_card_is_rejected_while_decomposition_is_pending(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(
            tmp_path, decomposition_required=True
        )

        results = coordinator.apply_actions(
            "wf-1", "trigger-1",
            [CreateCardAction(kind="design", title="Design it")],
        )

        assert results[0].validation_decision == "rejected"
        assert "decomposition required" in results[0].rejection_reason
        assert not results[0].applied
        assert [c.title for c in store.list_cards("wf-1")] == ["Investigate"]

    def test_analysis_and_decomposition_cards_are_still_allowed(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(
            tmp_path, decomposition_required=True
        )

        coordinator.apply_actions(
            "wf-1", "trigger-1",
            [
                CreateCardAction(kind="analysis", title="More analysis"),
                CreateCardAction(
                    kind="decomposition", title="Decompose",
                    eligible_roles=("pm",),
                ),
            ],
        )

        titles = {c.title for c in store.list_cards("wf-1")}
        assert {"More analysis", "Decompose"} <= titles

    def test_a_design_card_is_allowed_once_decomposition_gate_is_done(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(
            tmp_path, decomposition_required=True
        )
        store.create_card(
            WorkCard(
                id="gate-1", workflow_id="wf-1", kind="decomposition_gate",
                title="Approve decomposition", state="done",
            )
        )

        coordinator.apply_actions(
            "wf-1", "trigger-1",
            [CreateCardAction(kind="design", title="Design it")],
        )

        titles = {c.title for c in store.list_cards("wf-1")}
        assert "Design it" in titles

    def test_not_yet_done_gate_still_blocks(self, tmp_path: Path) -> None:
        coordinator, store = _coordinator(
            tmp_path, decomposition_required=True
        )
        store.create_card(
            WorkCard(
                id="gate-1", workflow_id="wf-1", kind="decomposition_gate",
                title="Approve decomposition", state="awaiting_human",
            )
        )

        results = coordinator.apply_actions(
            "wf-1", "trigger-1",
            [CreateCardAction(kind="design", title="Design it")],
        )

        assert results[0].validation_decision == "rejected"

    def test_a_skip_decomposition_workflow_is_exempt(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(
            tmp_path, decomposition_required=True, skip_decomposition=True,
        )

        coordinator.apply_actions(
            "wf-1", "trigger-1",
            [CreateCardAction(kind="design", title="Design it")],
        )

        titles = {c.title for c in store.list_cards("wf-1")}
        assert "Design it" in titles

    def test_disabled_by_default_allows_design_immediately(
        self, tmp_path: Path
    ) -> None:
        coordinator, store = _coordinator(tmp_path)

        coordinator.apply_actions(
            "wf-1", "trigger-1",
            [CreateCardAction(kind="design", title="Design it")],
        )

        titles = {c.title for c in store.list_cards("wf-1")}
        assert "Design it" in titles

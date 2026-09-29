"""Tests for the board application service (feature 026, T012).

``BoardService`` is the policy-mediated read/transition/event surface on
top of ``BoardStore`` — reads, revision increments, and safe event append,
rejecting any transition ``policy.is_valid_transition`` disallows.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models_board import WorkCard, Workflow
from app.models_board_records import AcceptedTaskIntake
from app.persistence.board_store import BoardStore, WorkflowAlreadyExistsError
from app.services.board.policy import PolicyViolation
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory


def _seeded(tmp_path: Path) -> BoardService:
    """A service over a store with one workflow and one ready card."""
    store = BoardStore(board_session_factory(tmp_path))
    store.create_workflow(
        Workflow(
            id="wf-1",
            source="github-issue",
            task_ref="owner/repo#1",
            repo="owner/repo",
            base_branch="main",
            source_visibility="public",
            title="Add a thing",
        )
    )
    store.create_card(
        WorkCard(
            id="card-1",
            workflow_id="wf-1",
            kind="analysis",
            title="Investigate",
            state="ready",
            eligible_roles=("developer",),
        )
    )
    return BoardService(store)


class TestReads:
    """The service exposes the same reads as the underlying store."""

    def test_get_card_returns_the_card(self, tmp_path: Path) -> None:
        service = _seeded(tmp_path)
        assert service.get_card("card-1").id == "card-1"

    def test_list_cards_returns_every_workflow_card(
        self, tmp_path: Path
    ) -> None:
        service = _seeded(tmp_path)
        cards = service.list_cards("wf-1")
        assert [c.id for c in cards] == ["card-1"]


class TestPolicyMediatedTransitions:
    """Every transition is validated against policy before it applies."""

    def test_valid_transition_applies_and_bumps_revision(
        self, tmp_path: Path
    ) -> None:
        service = _seeded(tmp_path)
        before = service.get_workflow("wf-1").revision

        updated = service.transition_card(
            "card-1", "cancelled", event_type="card.cancelled"
        )

        assert updated.state == "cancelled"
        assert service.get_workflow("wf-1").revision == before + 1

    def test_invalid_transition_is_rejected(self, tmp_path: Path) -> None:
        service = _seeded(tmp_path)
        with pytest.raises(PolicyViolation):
            service.transition_card(
                "card-1", "done", event_type="card.done"
            )
        # No mutation from the rejected transition.
        assert service.get_card("card-1").state == "ready"

    def test_transition_of_unknown_card_raises(self, tmp_path: Path) -> None:
        service = _seeded(tmp_path)
        with pytest.raises(PolicyViolation):
            service.transition_card(
                "missing", "cancelled", event_type="card.cancelled"
            )


class TestCreateWorkflowFromIntake:
    """A safety-cleared task becomes a workflow, with no cards yet.

    The initial understanding-gate card is *not* created here — it
    needs a ``HumanGateRecord`` alongside it, which only
    ``GatesService`` can write (``GatesService`` already holds a
    ``BoardService``, so the reverse import would cycle). See
    ``test_board_intake_gate.py`` for the caller (``IngestionService``)
    creating that gate and resolving it end to end (GitHub #42).
    """

    def test_creates_workflow_with_no_cards(self, tmp_path: Path) -> None:
        store = BoardStore(board_session_factory(tmp_path))
        service = BoardService(store)

        workflow = service.create_workflow_from_intake(
            AcceptedTaskIntake(
                source="github-issue",
                task_ref="owner/repo#9",
                repo="owner/repo",
                base_branch="main",
                source_visibility="public",
                title="Add a thing",
            )
        )

        assert service.list_cards(workflow.id) == []

    def test_records_a_workflow_created_event(self, tmp_path: Path) -> None:
        store = BoardStore(board_session_factory(tmp_path))
        service = BoardService(store)

        workflow = service.create_workflow_from_intake(
            AcceptedTaskIntake(
                source="github-issue",
                task_ref="owner/repo#9",
                repo="owner/repo",
                base_branch="main",
                source_visibility="public",
                title="Add a thing",
            )
        )

        events = service.list_events(workflow.id)
        assert [e.event_type for e in events] == ["workflow.created"]

    def test_duplicate_task_ref_is_rejected(self, tmp_path: Path) -> None:
        store = BoardStore(board_session_factory(tmp_path))
        service = BoardService(store)
        intake = AcceptedTaskIntake(
            source="github-issue",
            task_ref="owner/repo#9",
            repo="owner/repo",
            base_branch="main",
            source_visibility="public",
            title="Add a thing",
        )
        service.create_workflow_from_intake(intake)

        with pytest.raises(WorkflowAlreadyExistsError):
            service.create_workflow_from_intake(intake)


class TestEventAppend:
    """Every applied transition appends a safe board event."""

    def test_transition_records_an_event(self, tmp_path: Path) -> None:
        service = _seeded(tmp_path)
        service.transition_card(
            "card-1", "cancelled", event_type="card.cancelled"
        )
        events = service.list_events("wf-1")
        assert [e.event_type for e in events] == ["card.cancelled"]
        assert events[0].card_id == "card-1"


class TestOnMutationHook:
    """The coordinator's wake trigger fires on every committed mutation."""

    def test_workflow_creation_triggers_the_hook(
        self, tmp_path: Path
    ) -> None:
        store = BoardStore(board_session_factory(tmp_path))
        woken: list[str] = []
        service = BoardService(store, on_mutation=woken.append)

        workflow = service.create_workflow_from_intake(
            AcceptedTaskIntake(
                source="github-issue",
                task_ref="owner/repo#1",
                repo="owner/repo",
                base_branch="main",
                source_visibility="public",
                title="Add a thing",
            )
        )

        assert woken == [workflow.id]

    def test_transition_triggers_the_hook(self, tmp_path: Path) -> None:
        store = BoardStore(board_session_factory(tmp_path))
        store.create_workflow(
            Workflow(
                id="wf-1",
                source="github-issue",
                task_ref="owner/repo#1",
                repo="owner/repo",
                base_branch="main",
                source_visibility="public",
                title="Add a thing",
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
        woken: list[str] = []
        service = BoardService(store, on_mutation=woken.append)

        service.transition_card(
            "card-1", "cancelled", event_type="card.cancelled"
        )

        assert woken == ["wf-1"]

    def test_no_hook_configured_is_a_safe_no_op(self, tmp_path: Path) -> None:
        service = _seeded(tmp_path)
        service.transition_card(
            "card-1", "cancelled", event_type="card.cancelled"
        )


def test_a_card_round_trips_its_task_node_id(tmp_path: Path) -> None:
    """Ensure a card's task_node_id is persisted and read back."""
    store = BoardStore(board_session_factory(tmp_path))
    store.create_workflow(
        Workflow(
            id="wf-1",
            source="github-issue",
            task_ref="owner/repo#1",
            repo="owner/repo",
            base_branch="main",
            source_visibility="public",
            title="Add a thing",
        )
    )
    for card_id, node in (("card-t1", "t1"), ("card-plain", None)):
        store.create_card(
            WorkCard(
                id=card_id,
                workflow_id="wf-1",
                kind="implementation",
                title="Build it",
                state="ready",
                task_node_id=node,
            )
        )

    assert store.get_card("card-t1").task_node_id == "t1"
    assert store.get_card("card-plain").task_node_id is None

"""Revisioned intervention conflict and stale-action tests for
``InterventionsService`` (feature 026, T044).

Every intervention carries an ``expected_revision`` (board-api.md
"Intervention"): a stale request — the board moved on since the operator
last read it — is rejected outright rather than silently applying to a
board state the operator never actually saw.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.models_board import CardAction, ClaimRequest, WorkCard, Workflow
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.services.board.gates import GatesService
from app.services.board.interventions import (
    InterventionsService,
    InvalidInterventionError,
    StaleInterventionError,
)
from app.services.board.service import BoardService

_WORKFLOW = Workflow(
    id="wf-1",
    source="github-issue",
    task_ref="owner/repo#1",
    repo="owner/repo",
    base_branch="main",
    source_visibility="public",
    title="Add a thing",
)


def _factory(tmp_path: Path) -> sessionmaker:
    database = tmp_path / "board.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    return sessionmaker(bind=sa.create_engine(f"sqlite:///{database}"))


_Stores = tuple[
    InterventionsService, BoardStore, BoardClaimsStore, GatesService
]


def _service(tmp_path: Path) -> _Stores:
    factory = _factory(tmp_path)
    store = BoardStore(factory)
    claims_store = BoardClaimsStore(factory)
    board_service = BoardService(store)
    gate_store = BoardGateStore(factory)
    gates_service = GatesService(store, gate_store, board_service)
    store.create_workflow(_WORKFLOW)
    service = InterventionsService(
        store, claims_store, board_service, gates_service
    )
    return service, store, claims_store, gates_service


def _revision(store: BoardStore) -> int:
    return store.get_workflow("wf-1").revision


def _card(card_id: str = "card-1", **overrides: object) -> WorkCard:
    fields: dict[str, object] = {
        "id": card_id,
        "workflow_id": "wf-1",
        "kind": "analysis",
        "title": "Investigate",
        "state": "ready",
    }
    fields.update(overrides)
    return WorkCard(**fields)


def _claimed_card(
    store: BoardStore, claims_store: BoardClaimsStore, card_id: str = "card-1"
) -> None:
    """Seed a claimed card: ready + claimable, then immediately claimed."""
    store.create_card(_card(card_id, eligible_roles=("developer",)))
    claims_store.claim_card(ClaimRequest(card_id, "developer", 600))


class TestStaleRevision:
    """An intervention against an out-of-date revision is rejected."""

    def test_stale_expected_revision_raises(self, tmp_path: Path) -> None:
        service, store, _claims, _gates = _service(tmp_path)
        store.create_card(_card())
        stale = _revision(store) - 1

        with pytest.raises(StaleInterventionError):
            service.apply(
                "wf-1", "card-1", CardAction.CANCEL, expected_revision=stale
            )

    def test_current_revision_succeeds(self, tmp_path: Path) -> None:
        service, store, _claims, _gates = _service(tmp_path)
        store.create_card(_card())
        current = _revision(store)

        card = service.apply(
            "wf-1", "card-1", CardAction.CANCEL, expected_revision=current
        )

        assert card.state == "cancelled"


class TestRetry:
    """A failed card can be retried, but only a failed one."""

    def test_retry_moves_a_failed_card_to_ready(self, tmp_path: Path) -> None:
        service, store, _claims, _gates = _service(tmp_path)
        store.create_card(_card(state="failed"))

        card = service.apply(
            "wf-1",
            "card-1",
            CardAction.RETRY,
            expected_revision=_revision(store),
        )

        assert card.state == "ready"

    def test_retry_of_a_ready_card_is_rejected(self, tmp_path: Path) -> None:
        service, store, _claims, _gates = _service(tmp_path)
        store.create_card(_card())

        with pytest.raises(InvalidInterventionError):
            service.apply(
                "wf-1",
                "card-1",
                CardAction.RETRY,
                expected_revision=_revision(store),
            )


class TestCancel:
    """Cancel releases any active claim and cancels the card."""

    def test_cancel_of_a_claimed_card_releases_its_lease(
        self, tmp_path: Path
    ) -> None:
        service, store, claims_store, _gates = _service(tmp_path)
        _claimed_card(store, claims_store)

        card = service.apply(
            "wf-1",
            "card-1",
            CardAction.CANCEL,
            expected_revision=_revision(store),
        )

        assert card.state == "cancelled"
        assert not claims_store.release_claim("card-1")

    def test_cancel_of_an_already_done_card_is_rejected(
        self, tmp_path: Path
    ) -> None:
        service, store, _claims, _gates = _service(tmp_path)
        store.create_card(_card(state="done"))

        with pytest.raises(InvalidInterventionError):
            service.apply(
                "wf-1",
                "card-1",
                CardAction.CANCEL,
                expected_revision=_revision(store),
            )


class TestReassign:
    """Reassign frees a claimed card's lease and returns it to ready."""

    def test_reassign_releases_the_lease_and_returns_to_ready(
        self, tmp_path: Path
    ) -> None:
        service, store, claims_store, _gates = _service(tmp_path)
        _claimed_card(store, claims_store)

        card = service.apply(
            "wf-1",
            "card-1",
            CardAction.REASSIGN,
            expected_revision=_revision(store),
        )

        assert card.state == "ready"
        assert not claims_store.release_claim("card-1")

    def test_reassign_of_a_ready_card_is_rejected(
        self, tmp_path: Path
    ) -> None:
        service, store, _claims, _gates = _service(tmp_path)
        store.create_card(_card())

        with pytest.raises(InvalidInterventionError):
            service.apply(
                "wf-1",
                "card-1",
                CardAction.REASSIGN,
                expected_revision=_revision(store),
            )


class TestResolveGate:
    """Resolve-gate delegates to GatesService with the supplied decision."""

    def test_resolve_gate_approves_through_gates_service(
        self, tmp_path: Path
    ) -> None:
        service, store, _claims, gates = _service(tmp_path)
        gate = gates.create_gate(
            "wf-1",
            kind="understanding_gate",
            title="Confirm understanding",
            requested_decision="Approve?",
        )

        card = service.apply(
            "wf-1",
            gate.id,
            CardAction.RESOLVE_GATE,
            expected_revision=_revision(store),
            decision="approved",
        )

        assert card.state == "done"

    def test_resolve_gate_requires_a_decision_kwarg(
        self, tmp_path: Path
    ) -> None:
        service, store, _claims, gates = _service(tmp_path)
        gate = gates.create_gate(
            "wf-1",
            kind="understanding_gate",
            title="Confirm understanding",
            requested_decision="Approve?",
        )

        with pytest.raises(InvalidInterventionError):
            service.apply(
                "wf-1",
                gate.id,
                CardAction.RESOLVE_GATE,
                expected_revision=_revision(store),
            )


class TestRequestCoordinatorReview:
    """Requesting coordinator review creates a new coordinator-facing card."""

    def test_creates_a_coordinator_review_card(self, tmp_path: Path) -> None:
        service, store, _claims, _gates = _service(tmp_path)
        store.create_card(_card(state="review"))

        service.apply(
            "wf-1",
            "card-1",
            CardAction.REQUEST_COORDINATOR_REVIEW,
            expected_revision=_revision(store),
        )

        cards = store.list_cards("wf-1")
        review_cards = [c for c in cards if c.kind == "coordinator_review"]
        assert len(review_cards) == 1


class TestUnknownCard:
    """An intervention against an unknown card is rejected."""

    def test_unknown_card_raises(self, tmp_path: Path) -> None:
        service, store, _claims, _gates = _service(tmp_path)

        with pytest.raises(InvalidInterventionError):
            service.apply(
                "wf-1",
                "missing",
                CardAction.CANCEL,
                expected_revision=_revision(store),
            )

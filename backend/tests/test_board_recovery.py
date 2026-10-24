"""Restart/expiry/retry/escalate recovery tests for ``RecoveryService``
(feature 026, T036).

An abandoned claim's lease expiry is already durable
(``BoardClaimsStore.expire_leases``, covered by ``test_board_claims.py``);
this file covers the layer above it — that a recovered card's event is
visible on the board and wakes the coordinator (FR-004, FR-012), not just
that its row changed underneath.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models_board import ClaimRequest, WorkCard, Workflow
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
from app.services.board.recovery import RecoveryService
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory

_WORKFLOW = Workflow(
    id="wf-1",
    source="github-issue",
    task_ref="owner/repo#1",
    repo="owner/repo",
    base_branch="main",
    source_visibility="public",
    title="Add a thing",
)




def _service(
    tmp_path: Path, *, attempt_limit: int = 3
) -> tuple[RecoveryService, BoardStore, BoardClaimsStore, list[str]]:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    claims_store = BoardClaimsStore(factory)
    woken: list[str] = []
    board_service = BoardService(store, on_mutation=woken.append)
    store.create_workflow(_WORKFLOW)
    store.create_card(
        WorkCard(
            id="card-1",
            workflow_id="wf-1",
            kind="analysis",
            title="Investigate",
            state="ready",
            eligible_roles=("developer",),
            attempt_limit=attempt_limit,
        )
    )
    service = RecoveryService(claims_store, board_service, interval_seconds=60)
    return service, store, claims_store, woken


class TestRecoverExpiredClaims:
    """A restart-visible sweep recovers every abandoned claim."""

    def test_expired_claim_within_attempt_limit_is_retried(
        self, tmp_path: Path
    ) -> None:
        service, store, claims_store, _woken = _service(tmp_path)
        now = datetime.now(timezone.utc)
        claims_store.claim_card(
            ClaimRequest("card-1", "developer", 60), now=now
        )

        recovered = service.recover_expired_claims(
            now=now + timedelta(seconds=120)
        )

        assert recovered == ["card-1"]
        assert store.get_card("card-1").state == "ready"

    def test_recovery_wakes_the_coordinator(self, tmp_path: Path) -> None:
        service, _store, claims_store, woken = _service(tmp_path)
        now = datetime.now(timezone.utc)
        claims_store.claim_card(
            ClaimRequest("card-1", "developer", 60), now=now
        )

        service.recover_expired_claims(now=now + timedelta(seconds=120))

        assert woken == ["wf-1"]

    def test_recovery_records_a_retry_event(self, tmp_path: Path) -> None:
        service, store, claims_store, _woken = _service(tmp_path)
        now = datetime.now(timezone.utc)
        claims_store.claim_card(
            ClaimRequest("card-1", "developer", 60), now=now
        )

        service.recover_expired_claims(now=now + timedelta(seconds=120))

        events = store.list_events("wf-1")
        assert events[-1].event_type == "card.recovery_retry"
        assert events[-1].card_id == "card-1"

    def test_exhausted_attempt_limit_is_escalated_not_retried(
        self, tmp_path: Path
    ) -> None:
        service, store, claims_store, _woken = _service(
            tmp_path, attempt_limit=1
        )
        now = datetime.now(timezone.utc)
        claims_store.claim_card(
            ClaimRequest("card-1", "developer", 60), now=now
        )

        service.recover_expired_claims(now=now + timedelta(seconds=120))

        assert store.get_card("card-1").state == "failed"
        events = store.list_events("wf-1")
        assert events[-1].event_type == "card.recovery_escalated"

    def test_no_expired_claims_is_a_safe_no_op(self, tmp_path: Path) -> None:
        service, _store, _claims_store, woken = _service(tmp_path)

        recovered = service.recover_expired_claims()

        assert recovered == []
        assert woken == []

    def test_unexpired_claim_is_left_alone(self, tmp_path: Path) -> None:
        service, store, claims_store, woken = _service(tmp_path)
        now = datetime.now(timezone.utc)
        claims_store.claim_card(
            ClaimRequest("card-1", "developer", 600), now=now
        )

        recovered = service.recover_expired_claims(
            now=now + timedelta(seconds=10)
        )

        assert recovered == []
        assert store.get_card("card-1").state == "claimed"
        assert woken == []

"""Atomic claim, write-lease, and lease-expiry recovery tests (feature 026).

Exercises ``app.persistence.board_claims_store.BoardClaimsStore`` (claims)
alongside ``app.persistence.board_store.BoardStore`` (reads/seeding)
against a real, migrated SQLite database — the same convention as the
existing store tests (e.g. ``test_child_task_store.py``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models_board import ClaimRequest, WorkCard, Workflow
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
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




@dataclass(frozen=True)
class _Stores:
    """A board store (reads/seeding) paired with its claims store."""

    board: BoardStore
    claims: BoardClaimsStore

    def get_card(self, card_id: str) -> WorkCard | None:
        return self.board.get_card(card_id)


def _seeded_store(
    tmp_path: Path, *, card_id: str = "card-1", attempt_limit: int = 3
) -> _Stores:
    """A store pair with one workflow and one ready card."""
    factory = board_session_factory(tmp_path)
    board = BoardStore(factory)
    claims = BoardClaimsStore(factory)
    board.create_workflow(_WORKFLOW)
    board.create_card(
        WorkCard(
            id=card_id,
            workflow_id="wf-1",
            kind="analysis",
            title="Investigate",
            state="ready",
            eligible_roles=("developer",),
            attempt_limit=attempt_limit,
        )
    )
    return _Stores(board, claims)


class TestAtomicClaim:
    """Claiming a card is atomic and rejects an already-claimed card."""

    def test_claim_ready_card_succeeds(self, tmp_path: Path) -> None:
        store = _seeded_store(tmp_path)
        outcome = store.claims.claim_card(
            ClaimRequest("card-1", "developer", lease_seconds=60)
        )
        assert outcome.success
        assert outcome.attempt_sequence == 1
        assert store.get_card("card-1").state == "claimed"

    def test_claiming_an_already_claimed_card_fails(
        self, tmp_path: Path
    ) -> None:
        store = _seeded_store(tmp_path)
        store.claims.claim_card(ClaimRequest("card-1", "developer", 60))
        second = store.claims.claim_card(
            ClaimRequest("card-1", "architect", 60)
        )
        assert not second.success
        assert second.reason == "not_ready"

    def test_claiming_an_unknown_card_fails(self, tmp_path: Path) -> None:
        store = _seeded_store(tmp_path)
        outcome = store.claims.claim_card(
            ClaimRequest("missing", "developer", 60)
        )
        assert not outcome.success


class TestWorkspaceWriteLease:
    """At most one writer holds a repository's workspace lease."""

    def test_second_writer_for_same_repo_is_rejected(
        self, tmp_path: Path
    ) -> None:
        store = _seeded_store(tmp_path)
        store.board.create_card(
            WorkCard(
                id="card-2",
                workflow_id="wf-1",
                kind="implementation",
                title="Implement",
                state="ready",
                eligible_roles=("coder",),
                workspace_permission="write",
            )
        )
        first = store.claims.claim_card(
            ClaimRequest(
                "card-1", "coder", 60, workspace_repo="owner/repo"
            )
        )
        second = store.claims.claim_card(
            ClaimRequest(
                "card-2", "coder", 60, workspace_repo="owner/repo"
            )
        )
        assert first.success
        assert not second.success
        assert second.reason == "workspace_lease_unavailable"

    def test_read_only_claims_do_not_contend_for_a_workspace_lease(
        self, tmp_path: Path
    ) -> None:
        store = _seeded_store(tmp_path)
        store.board.create_card(
            WorkCard(
                id="card-2",
                workflow_id="wf-1",
                kind="analysis",
                title="Investigate more",
                state="ready",
                eligible_roles=("architect",),
            )
        )
        first = store.claims.claim_card(ClaimRequest("card-1", "developer", 60))
        second = store.claims.claim_card(
            ClaimRequest("card-2", "architect", 60)
        )
        assert first.success
        assert second.success


class TestStaleResult:
    """A late result after a claim's lease expired must not win."""

    def test_completion_after_reclaim_is_rejected_as_stale(
        self, tmp_path: Path
    ) -> None:
        store = _seeded_store(tmp_path)
        now = datetime.now(timezone.utc)
        first = store.claims.claim_card(
            ClaimRequest("card-1", "developer", 60), now=now
        )
        store.claims.expire_leases(now=now + timedelta(seconds=120))
        second = store.claims.claim_card(
            ClaimRequest("card-1", "developer", 60),
            now=now + timedelta(seconds=121),
        )
        assert second.success
        assert second.attempt_sequence == first.attempt_sequence + 1

        stale = store.claims.complete_attempt(
            "card-1",
            first.attempt_sequence,
            result="late result",
            new_state="review",
        )
        assert not stale.success
        assert stale.reason == "stale"
        # The newer attempt's claim is untouched by the stale completion.
        assert store.get_card("card-1").state == "claimed"

    def test_completion_of_the_active_attempt_succeeds(
        self, tmp_path: Path
    ) -> None:
        store = _seeded_store(tmp_path)
        claim = store.claims.claim_card(ClaimRequest("card-1", "developer", 60))
        outcome = store.claims.complete_attempt(
            "card-1",
            claim.attempt_sequence,
            result="done",
            new_state="review",
        )
        assert outcome.success
        assert store.get_card("card-1").state == "review"


class TestLeaseExpiryRecovery:
    """An abandoned claim is recorded as interrupted and made retryable."""

    def test_expired_lease_marks_attempt_interrupted(
        self, tmp_path: Path
    ) -> None:
        store = _seeded_store(tmp_path)
        now = datetime.now(timezone.utc)
        store.claims.claim_card(
            ClaimRequest("card-1", "developer", 60), now=now
        )

        expired = store.claims.expire_leases(now=now + timedelta(seconds=120))

        assert expired == ["card-1"]

    def test_expired_lease_returns_card_to_ready_within_attempt_limit(
        self, tmp_path: Path
    ) -> None:
        store = _seeded_store(tmp_path)
        now = datetime.now(timezone.utc)
        store.claims.claim_card(
            ClaimRequest("card-1", "developer", 60), now=now
        )

        store.claims.expire_leases(now=now + timedelta(seconds=120))

        assert store.get_card("card-1").state == "ready"

    def test_expired_lease_beyond_attempt_limit_fails_the_card(
        self, tmp_path: Path
    ) -> None:
        store = _seeded_store(tmp_path, attempt_limit=1)
        now = datetime.now(timezone.utc)
        store.claims.claim_card(
            ClaimRequest("card-1", "developer", 60), now=now
        )

        store.claims.expire_leases(now=now + timedelta(seconds=120))

        assert store.get_card("card-1").state == "failed"

    def test_unexpired_lease_is_left_alone(self, tmp_path: Path) -> None:
        store = _seeded_store(tmp_path)
        now = datetime.now(timezone.utc)
        store.claims.claim_card(
            ClaimRequest("card-1", "developer", 600), now=now
        )

        expired = store.claims.expire_leases(now=now + timedelta(seconds=10))

        assert expired == []
        assert store.get_card("card-1").state == "claimed"


class TestActiveLease:
    """The current holder of a claimed card is readable directly."""

    def test_unclaimed_card_has_no_active_lease(self, tmp_path: Path) -> None:
        store = _seeded_store(tmp_path)
        assert store.claims.get_active_lease("card-1") is None

    def test_claimed_card_reports_its_holder(self, tmp_path: Path) -> None:
        store = _seeded_store(tmp_path)
        store.claims.claim_card(ClaimRequest("card-1", "developer", 600))

        lease = store.claims.get_active_lease("card-1")

        assert lease is not None
        assert lease.specialist_id == "developer"
        assert lease.attempt_sequence == 1

"""Claims hold under concurrent claimants (GitHub #87)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlalchemy as sa

from app.models_board import ClaimRequest, WorkCard
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
from app.persistence.board_tables import BoardCardRow, BoardClaimLeaseRow
from tests.board_test_support import board_session_factory, seed_workflows
from tests.concurrency_support import contend


def _writers(tmp_path: Path) -> tuple[BoardClaimsStore, sa.Engine]:
    factory = board_session_factory(tmp_path)
    seed_workflows(factory, "wf-1")
    board = BoardStore(factory)
    for card_id in ("card-1", "card-2"):
        board.create_card(WorkCard(
            id=card_id, workflow_id="wf-1", kind="implementation",
            title="Implement", state="ready", eligible_roles=("coder",),
            workspace_permission="write",
        ))
    return BoardClaimsStore(factory), factory.kw["bind"]


def _hold_repository(db: sa.Connection) -> None:
    """A writer's claim of card-1, left uncommitted."""
    db.execute(sa.insert(BoardClaimLeaseRow).values(
        card_id="card-1", attempt_sequence=1,
        holder_specialist_id="coder", workspace_repo="o/r",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))


def test_a_repository_taken_meanwhile_is_unavailable(tmp_path: Path) -> None:
    """Ensure a writer that claims while another writer's claim of the
    same repository commits backs off instead of failing or sharing."""
    claims, engine = _writers(tmp_path)

    outcome = contend(engine, _hold_repository, lambda: claims.claim_card(
        ClaimRequest("card-2", "coder", 60, workspace_repo="o/r")
    ))

    assert outcome.reason == "workspace_lease_unavailable"


def _sweep_card_1(db: sa.Connection) -> None:
    """What recovery does to card-1's expired claim, left uncommitted."""
    db.execute(sa.delete(BoardClaimLeaseRow).where(
        BoardClaimLeaseRow.card_id == "card-1"
    ))
    db.execute(sa.update(BoardCardRow).where(
        BoardCardRow.id == "card-1"
    ).values(state="ready"))


def test_a_completion_after_recovery_took_the_claim_is_stale(
    tmp_path: Path,
) -> None:
    """Ensure a result that arrives while recovery frees its claim does
    not also advance the card."""
    claims, engine = _writers(tmp_path)
    claims.claim_card(ClaimRequest("card-1", "coder", 60))

    outcome = contend(engine, _sweep_card_1, lambda: claims.complete_attempt(
        "card-1", 1, result="late", new_state="review"
    ))

    assert outcome.reason == "stale"
    with engine.connect() as db:
        state = db.scalar(sa.select(BoardCardRow.state).where(
            BoardCardRow.id == "card-1"
        ))
    assert state == "ready"

"""A workflow's counters survive concurrent writers (GitHub #87).

Each test lets a second transaction change the same workflow row and
commit while the store's call waits on it; a store that read the row
and wrote its own sum back would lose that change.
"""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from app.persistence.board_store import BoardStore
from app.persistence.board_tables import BoardWorkflowRow
from tests.board_test_support import board_session_factory, seed_workflows
from tests.concurrency_support import contend

#: A new workflow's revision (1) after one bump from each transaction.
_AFTER_TWO_BUMPS = 3
#: The repair rounds two observed failures make.
_TWO_ROUNDS = 2


def _store(tmp_path: Path) -> tuple[BoardStore, sa.Engine]:
    factory = board_session_factory(tmp_path)
    seed_workflows(factory, "wf-1")
    return BoardStore(factory), factory.kw["bind"]


def _bump(**values: object) -> sa.Update:
    return (
        sa.update(BoardWorkflowRow)
        .where(BoardWorkflowRow.id == "wf-1")
        .values(**values)
    )


def test_concurrent_revision_bumps_both_count(tmp_path: Path) -> None:
    """Ensure a revision bump that waits on another adds to its result."""
    store, engine = _store(tmp_path)

    revision = contend(
        engine,
        lambda db: db.execute(
            _bump(revision=BoardWorkflowRow.revision + 1)
        ),
        lambda: store.bump_workflow_revision("wf-1"),
    )

    assert revision == _AFTER_TWO_BUMPS
    assert store.get_workflow("wf-1").revision == _AFTER_TWO_BUMPS


def test_concurrent_ci_failures_both_count(tmp_path: Path) -> None:
    """Ensure two observed CI failures make two repair rounds."""
    store, engine = _store(tmp_path)

    repair_round = contend(
        engine,
        lambda db: db.execute(_bump(
            ci_status="failed",
            ci_repair_round=BoardWorkflowRow.ci_repair_round + 1,
        )),
        lambda: store.record_ci_status("wf-1", "failed"),
    )

    assert repair_round == _TWO_ROUNDS
    assert store.get_workflow("wf-1").ci_repair_round == _TWO_ROUNDS


def test_a_passing_ci_status_keeps_the_repair_round(tmp_path: Path) -> None:
    """Ensure only a failure counts as a repair round."""
    store, _ = _store(tmp_path)
    store.record_ci_status("wf-1", "failed")

    assert store.record_ci_status("wf-1", "passed") == 1
    assert store.get_workflow("wf-1").ci_status == "passed"

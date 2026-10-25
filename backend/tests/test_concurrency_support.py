"""The race-test helper fails instead of hanging (Copilot review, #91)."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests import concurrency_support
from tests.board_test_support import board_session_factory, seed_workflows

#: Longer than a clean failure takes; shorter than a hang.
_JOIN_SECONDS = 15.0

_LOCK_ROW = sa.text(
    "UPDATE board_workflow SET title = title WHERE id = 'wf-1'"
)


def test_a_failure_while_the_contender_waits_rolls_the_holder_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure contend raises, not hangs, when it fails mid-wait.

    The contender is blocked on the holder's row lock when the wait step
    fails; the holder must release the lock before the worker is joined.
    """
    factory = board_session_factory(tmp_path)
    seed_workflows(factory, "wf-1")
    engine = factory.kw["bind"]
    original_wait = concurrency_support._wait_until_waiting

    def wait_then_fail(watched_engine: sa.Engine, future: object) -> None:
        original_wait(watched_engine, future)
        raise RuntimeError("failed while the contender waits")

    monkeypatch.setattr(
        concurrency_support, "_wait_until_waiting", wait_then_fail
    )

    def contender() -> None:
        with engine.begin() as conn:
            conn.execute(_LOCK_ROW)

    raised: list[BaseException] = []

    def run() -> None:
        try:
            concurrency_support.contend(
                engine, lambda holder: holder.execute(_LOCK_ROW), contender
            )
        except RuntimeError as exc:
            raised.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(_JOIN_SECONDS)

    assert not worker.is_alive(), "contend hung"
    assert [str(e) for e in raised] == ["failed while the contender waits"]

"""Two transactions interleaved on purpose, for the persistence race tests.

A race under PostgreSQL's READ COMMITTED needs one transaction to hold a
row (or a unique key) while another reads and writes it. Waiting a while
and hoping proves nothing; instead :func:`contend` lets the holder commit
only once the contender is seen waiting on the holder's lock in
``pg_stat_activity``, so every run takes the same interleaving.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TypeVar

import sqlalchemy as sa

_T = TypeVar("_T")

#: How long a contender may take to reach the lock before the test fails.
_DEADLINE_SECONDS = 10.0

_WAITING = sa.text(
    "SELECT count(*) FROM pg_stat_activity"
    " WHERE datname = current_database() AND wait_event_type = 'Lock'"
)


def contend(
    engine: sa.Engine,
    hold: Callable[[sa.Connection], object],
    contender: Callable[[], _T],
) -> _T:
    """
    Run *contender* while another transaction holds what *hold* wrote.

    The holder's transaction stays open until *contender* waits on one of
    its locks, then commits; *contender* then carries on against the
    committed result.

    :param engine: The database both transactions use.
    :param hold: Writes the holder's (uncommitted) rows.
    :param contender: The code under test, run in a thread.
    :returns: What *contender* returned.
    :raises TimeoutError: If *contender* never waits on the holder.
    """
    with engine.connect() as holder, ThreadPoolExecutor(1) as pool:
        hold(holder)
        future = pool.submit(contender)
        _wait_until_waiting(engine, future)
        holder.commit()
        return future.result(timeout=_DEADLINE_SECONDS)


def _wait_until_waiting(engine: sa.Engine, future: Future) -> None:
    """Return once a transaction waits on a lock, or *future* is done."""
    deadline = time.monotonic() + _DEADLINE_SECONDS
    with engine.connect() as watcher:
        while not future.done():
            if watcher.execute(_WAITING).scalar_one() > 0:
                return
            if time.monotonic() > deadline:
                raise TimeoutError("the contender never waited on a lock")
            watcher.rollback()
            time.sleep(0.01)

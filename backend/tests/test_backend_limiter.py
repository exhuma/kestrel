"""Tests for process-local backend concurrency admission."""
from __future__ import annotations

import asyncio

import pytest

from app.backends.limiter import BackendLimiter

_PARALLELISM = 3
_TASK_COUNT = 5

@pytest.mark.asyncio
async def test_limiter_serializes_calls_at_the_default_cap() -> None:
    """Ensure one limiter permits only one active call by default."""
    limiter = BackendLimiter()
    started = asyncio.Event()
    release = asyncio.Event()
    active = 0
    maximum = 0

    async def run() -> None:
        """Hold a limiter slot until the test releases it."""
        nonlocal active, maximum
        async with limiter.slot():
            active += 1
            maximum = max(maximum, active)
            started.set()
            await release.wait()
            active -= 1

    first = asyncio.create_task(run())
    await started.wait()
    second = asyncio.create_task(run())
    await asyncio.sleep(0)
    assert maximum == 1
    release.set()
    await asyncio.gather(first, second)
    assert maximum == 1


@pytest.mark.asyncio
async def test_limiter_allows_its_configured_parallelism() -> None:
    """Ensure a limiter permits the configured number of active calls."""
    limiter = BackendLimiter(_PARALLELISM)
    entered = 0
    maximum = 0
    release = asyncio.Event()

    async def run() -> None:
        """Record entry, then hold a limiter slot until released."""
        nonlocal entered, maximum
        async with limiter.slot():
            entered += 1
            maximum = max(maximum, entered)
            await release.wait()
            entered -= 1

    tasks = [asyncio.create_task(run()) for _ in range(_TASK_COUNT)]
    while entered < _PARALLELISM:
        await asyncio.sleep(0)
    assert maximum == _PARALLELISM
    release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_consume_a_slot() -> None:
    """Ensure cancelling a queued call leaves the permit available."""
    limiter = BackendLimiter()
    release = asyncio.Event()

    async def hold() -> None:
        """Occupy the sole slot until released."""
        async with limiter.slot():
            await release.wait()

    holder = asyncio.create_task(hold())
    await asyncio.sleep(0)
    waiter = asyncio.create_task(hold())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    await holder
    async with limiter.slot():
        pass


@pytest.mark.asyncio
async def test_limiter_reports_queue_and_admission() -> None:
    """Ensure a waiter reports queuing before it receives a slot."""
    limiter = BackendLimiter()
    changes: list[bool] = []
    release = asyncio.Event()

    async def hold() -> None:
        """Occupy the sole slot until released."""
        async with limiter.slot():
            await release.wait()

    async def wait() -> None:
        """Acquire the slot after the holder releases it."""
        async with limiter.slot(changes.append):
            pass

    holder = asyncio.create_task(hold())
    await asyncio.sleep(0)
    waiter = asyncio.create_task(wait())
    await asyncio.sleep(0)
    assert changes == [True]
    release.set()
    await asyncio.gather(holder, waiter)
    assert changes == [True, False]

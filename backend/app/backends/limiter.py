"""Per-backend async concurrency admission."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable


class BackendLimiter:
    """Limit in-flight turns for one configured backend instance."""

    def __init__(self, max_concurrency: int = 1) -> None:
        """Create a limiter with the given number of available slots."""
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @asynccontextmanager
    async def slot(
        self,
        on_queue_change: Callable[[bool], None] | None = None,
    ) -> AsyncIterator[None]:
        """Yield one slot and report when a caller queues or is admitted."""
        if self._semaphore.locked() and on_queue_change is not None:
            on_queue_change(True)
        await self._semaphore.acquire()
        if on_queue_change is not None:
            on_queue_change(False)
        try:
            yield
        finally:
            self._semaphore.release()

    async def acquire(self) -> None:
        """Wait to acquire a slot for a detached background turn."""
        await self._semaphore.acquire()

    def release(self) -> None:
        """Release a slot held by a detached background turn."""
        self._semaphore.release()

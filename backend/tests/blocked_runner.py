"""Controllable backend double for testing in-flight workflow turns."""
from __future__ import annotations

import asyncio

from tests.conftest import _FakeRunner


class BlockedRunner(_FakeRunner):
    """Pause one configured backend turn until the test releases it."""

    def __init__(self, sessions, outputs, blocked_call: int) -> None:
        """Build a canned backend that blocks before the selected turn."""
        super().__init__(sessions, outputs)
        self.blocked_call = blocked_call
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_turn(self, req, on_session_id=None, on_queue_change=None):
        """Wait at the selected call, then return its canned result."""
        del on_queue_change
        if len(self.calls) == self.blocked_call:
            self.started.set()
            await self.release.wait()
        return await super().run_turn(req, on_session_id)

"""Frees what opencode holds for a directory once no turn uses it.

``opencode serve`` keeps state per directory (language servers, MCP
clients, watchers) until told otherwise, and every workflow has its own
worktree, so a long-running server otherwise grows until it is killed
for memory. Sessions are stored separately and survive a release.
"""
from __future__ import annotations

import logging
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx

from app.backends.base import BackendUnavailable

_logger = logging.getLogger(__name__)


class DirectoryReleases:
    """Counts the turns in each directory and releases it after the last."""

    def __init__(self, request: Callable[..., Awaitable[object]]) -> None:
        """
        :param request: ``OpenCodeBackend._request``.
        """
        self._request = request
        self._turns: Counter[str] = Counter()

    @asynccontextmanager
    async def turn(self, directory: str) -> AsyncIterator[None]:
        """Hold *directory* for one turn; release it after a turn that
        finished. A turn that failed or was cancelled leaves it: opencode
        may still be stopping it.

        :param directory: The turn's working directory (``""`` for none).
        """
        self._turns[directory] += 1
        try:
            yield
        finally:
            self._turns[directory] -= 1
        if directory and not self._turns[directory]:
            del self._turns[directory]
            await self._release(directory)

    async def _release(self, directory: str) -> None:
        """Best effort: only memory is at stake, and an opencode without
        the endpoint must not fail a turn that has already finished."""
        try:
            await self._request(
                "POST", "/instance/dispose", directory=directory
            )
        except (httpx.HTTPError, BackendUnavailable) as exc:
            _logger.debug(
                "opencode did not release %s", directory, exc_info=exc
            )

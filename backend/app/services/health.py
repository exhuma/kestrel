"""Source health checks (feature 014).

Whether each configured task-source/code-host adapter is currently
reachable and authenticated — a binary healthy/unhealthy signal, kept
fresh by a background cycle (mirroring the existing ``PollSource``
pattern) plus an on-demand manual refresh. Deliberately not persisted
(``specs/014-source-health-checks/research.md`` R5): a value from before
a restart is not meaningfully more trustworthy than "unknown", and the
background cycle re-establishes real status within one cadence interval
of startup.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from typing import Awaitable, Callable

from app.config import get_settings
from app.ports import WorkItem
from app.services.workflows import get_workflow_service
from app.storage.health_bus import HealthBus

_log = logging.getLogger("kestrel.health")

#: One entry's check: no arguments, never raises, ``True`` iff healthy.
CheckFn = Callable[[], Awaitable[bool]]


class HealthState(str, Enum):
    """A source's current status (data-model.md)."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


@dataclass
class SourceHealth:
    """One registered entry's current status."""

    name: str
    state: HealthState = HealthState.UNKNOWN
    checked_at: datetime | None = None


class HealthStore:
    """In-memory, process-lifetime health status per registered entry."""

    def __init__(self, names: list[str]) -> None:
        self._entries = {name: SourceHealth(name=name) for name in names}

    def list_all(self) -> list[SourceHealth]:
        """Every entry, in registration order."""
        return list(self._entries.values())

    def get(self, name: str) -> SourceHealth | None:
        """One entry by name, or ``None`` if not registered."""
        return self._entries.get(name)

    def set(self, name: str, healthy: bool) -> None:
        """Record a completed check's outcome for ``name``."""
        entry = self._entries.get(name)
        if entry is None:
            return
        entry.state = HealthState.HEALTHY if healthy else HealthState.UNHEALTHY
        entry.checked_at = datetime.now(timezone.utc)


class HealthPollService:
    """Runs every registered entry's check, on a cycle or on demand.

    Satisfies the ``PollSource`` protocol (``app/services/poll_source.py``)
    so it starts/stops through the exact same lifespan plumbing as every
    other background poll loop — no new startup/shutdown code
    (research.md R3).
    """

    def __init__(self, checks: list[tuple[str, CheckFn]]) -> None:
        self._names = [name for name, _ in checks]
        self._check_by_name = dict(checks)
        self.store = HealthStore(self._names)
        self.bus = HealthBus()
        self._locks = {name: asyncio.Lock() for name in self._names}

    @property
    def name(self) -> str:
        """Display label for the poll dry-run listing."""
        return "health"

    async def list_work_items(self) -> list[WorkItem]:
        """No dry-run listing: this source re-checks adapters, not
        tickets awaiting ingestion (required by the ``PollSource``
        protocol)."""
        return []

    async def run_cycle(self) -> None:
        """Check every registered entry once, sequentially."""
        for name in self._names:
            await self._check_one(name)
        self.bus.publish()

    async def refresh(self, name: str) -> bool:
        """Recheck one entry immediately; ``False`` if unregistered."""
        if name not in self._locks:
            return False
        await self._check_one(name)
        self.bus.publish()
        return True

    async def _check_one(self, name: str) -> None:
        """Run one entry's check, deduped against any in-flight run for
        the same entry (background cycle vs. manual refresh — FR-005)."""
        lock = self._locks[name]
        if lock.locked():
            return
        async with lock:
            check_fn = self._check_by_name[name]
            timeout = get_settings().health_check_timeout_seconds
            try:
                healthy = await asyncio.wait_for(check_fn(), timeout)
            except Exception:  # noqa: BLE001 — a bad check must not raise
                _log.exception("health check failed for %s", name)
                healthy = False
            self.store.set(name, healthy)

    async def run_forever(self) -> None:
        """Run a cycle immediately, then every configured interval."""
        while True:
            await self.run_cycle()
            await asyncio.sleep(get_settings().health_check_interval_seconds)


def _health_checks() -> list[tuple[str, CheckFn]]:
    """The hand-curated list of what to check (research.md R6).

    Reuses the exact adapter instances ``WorkflowService`` already holds
    — not fresh ones — so a GitHub profile's task-source and code-host
    roles, which share one underlying ``GitHubClient``, are registered
    once rather than as two indicators for the same connection. Only
    registered for a role that is actually configured (``settings``'s own
    ``*_sources()`` helpers), so an operator who never set up GitHub
    never sees a "github" entry at all.
    """
    settings = get_settings()
    service = get_workflow_service()
    checks: list[tuple[str, CheckFn]] = []
    if settings.github_sources():
        gh = service.sources["github-issue"].check_health
        checks.append(("github", gh))
    if settings.jira_sources():
        checks.append(("jira", service.sources["jira-issue"].check_health))
        code_host_label = settings.jira_sources()[0].code_host
        code_host_check = service.code_hosts["jira-issue"].check_health
        checks.append((code_host_label, code_host_check))
    if settings.fixture_sources():
        fixture = service.sources["fixture-issue"].check_health
        checks.append(("fixture", fixture))
    return checks


@lru_cache
def get_health_poll_service() -> HealthPollService:
    """Return the process-wide HealthPollService singleton."""
    return HealthPollService(_health_checks())

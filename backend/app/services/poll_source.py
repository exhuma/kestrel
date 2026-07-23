"""Source-agnostic poll listing: enumerate configured task sources.

A ``PollSource`` is the poll-time role shared by the GitHub reconcile service
and the Jira poll service (feature 004): it can list its qualifying work items
without ingesting (for ``python -m app poll``) and run its background loop. This
module is what both the lifespan and the CLI iterate, so the "which sources are
configured" logic lives in exactly one place.
"""
from __future__ import annotations

from typing import Protocol

from app.config import Settings
from app.ports import WorkItem
from app.services.jira_poll import get_jira_poll_services
from app.services.reconcile import get_reconcile_services


class PollSource(Protocol):
    """A configured source: list its items (dry-run) and run its loop."""

    @property
    def name(self) -> str:
        """Human-readable label for the dry-run listing."""

    async def list_work_items(self) -> list[WorkItem]:
        """Return this source's qualifying items; starts no run."""

    async def run_forever(self) -> None:
        """Run this source's poll loop until cancelled."""


def configured_poll_sources(settings: Settings) -> list[PollSource]:
    """Every configured task source as a ``PollSource`` (github + jira)."""
    sources: list[PollSource] = []
    if settings.github_sources():
        sources.extend(get_reconcile_services())
    if settings.jira_sources():
        sources.extend(get_jira_poll_services())
    return sources

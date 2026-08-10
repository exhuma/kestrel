"""Fixture poll ingestion: pick up local task files (feature 008).

Poll-only, mirroring the shape of ``JiraPollService``/``ReconcileService``:
each cycle lists the JSON files in a configured fixture source's
``fixtures_dir`` and funnels each through the shared source-neutral
ingestion guard (``IngestionService.maybe_start_run``), which already
handles dedup/dismissal — no extra bookkeeping needed here. One service
instance is bound to one ``fixture`` task source.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from functools import lru_cache

from app.config import get_settings
from app.config_models import TaskSourceConfig
from app.ports import WorkItem
from app.services.ingestion import IngestionService, get_ingestion_service

_log = logging.getLogger("kestrel.fixture_poll")


def _fixture_slugs(fixtures_dir: str) -> list[str]:
    """Sorted stems of every ``*.json`` fixture file, for determinism."""
    if not os.path.isdir(fixtures_dir):
        return []
    return sorted(
        name.removesuffix(".json")
        for name in os.listdir(fixtures_dir)
        if name.endswith(".json")
    )


def _read_fixture(fixtures_dir: str, slug: str) -> dict | None:
    path = os.path.join(fixtures_dir, f"{slug}.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        _log.warning("fixture: could not read %s", path)
        return None


class FixturePollService:
    """Runs poll cycles over one configured fixture task source."""

    def __init__(
        self, source: TaskSourceConfig, ingestion: IngestionService
    ) -> None:
        self.source = source
        self.ingestion = ingestion

    @property
    def name(self) -> str:
        """Display label for the poll dry-run listing."""
        return f"fixture [{self.source.fixtures_dir}]"

    async def run_cycle(self) -> None:
        """Poll the source once; failures are isolated per fixture file."""
        slugs = _fixture_slugs(self.source.fixtures_dir)
        _log.info("fixture: %d task(s)", len(slugs))
        for slug in slugs:
            await self._ingest(slug)

    async def _ingest(self, slug: str) -> None:
        data = _read_fixture(self.source.fixtures_dir, slug)
        if data is None or not data.get("code_repo"):
            _log.info("ingest outcome=unresolved-repo fixture:%s", slug)
            return
        try:
            await self.ingestion.maybe_start_run(
                source="fixture-issue",
                task_ref=f"fixture:{slug}",
                code_repo=data["code_repo"],
                base_branch=data.get("base_branch"),
            )
        except Exception:  # noqa: BLE001 — one task must not stop the rest
            _log.exception("fixture: start failed for fixture:%s", slug)

    async def list_work_items(self) -> list[WorkItem]:
        """List every fixture task; starts no run."""
        items: list[WorkItem] = []
        for slug in _fixture_slugs(self.source.fixtures_dir):
            data = _read_fixture(self.source.fixtures_dir, slug) or {}
            items.append(
                WorkItem(
                    source="fixture-issue",
                    ref=f"fixture:{slug}",
                    title=data.get("title", ""),
                    code_repo=data.get("code_repo"),
                    base_branch=data.get("base_branch"),
                )
            )
        return items

    async def run_forever(self) -> None:
        """Run a cycle immediately, then every configured interval."""
        while True:
            await self.run_cycle()
            await asyncio.sleep(get_settings().poll_interval_seconds)


@lru_cache
def get_fixture_poll_services() -> tuple[FixturePollService, ...]:
    """One FixturePollService per configured fixture task source."""
    return tuple(
        FixturePollService(source, get_ingestion_service())
        for source in get_settings().fixture_sources()
    )

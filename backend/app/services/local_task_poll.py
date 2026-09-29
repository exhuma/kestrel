"""Local task poll ingestion: pick up local task files.

Poll-only, mirroring the shape of ``JiraPollService``/``ReconcileService``:
each cycle lists the JSON files in a configured local source's ``tasks_dir``
and funnels each through the shared source-neutral
ingestion guard (``IngestionService.maybe_start_run``), which already
handles dedup/dismissal — no extra bookkeeping needed here. One service
instance is bound to one ``local`` task source.
"""

from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.config_models import TaskSourceConfig
from app.ports import WorkItem
from app.services.ingestion import IngestionService, get_ingestion_service
from app.services.local_task_source import local_task_ref

_log = logging.getLogger("kestrel.local_task_poll")


def _task_dirs(tasks_dir: str) -> list[Path]:
    """Return task directories recursively in deterministic path order."""
    root = Path(tasks_dir)
    if not root.is_dir():
        return []
    return sorted(path.parent for path in root.rglob("task.json"))


def _read_local_task(path: Path) -> dict | None:
    """Read one task's metadata, logging malformed local task data."""
    try:
        with (path / "task.json").open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        _log.warning("local task: could not read %s", path)
        return None


class LocalTaskPollService:
    """Runs poll cycles over one configured local task source."""

    def __init__(
        self, source: TaskSourceConfig, ingestion: IngestionService
    ) -> None:
        self.source = source
        self.ingestion = ingestion

    @property
    def name(self) -> str:
        """Display label for the poll dry-run listing."""
        return f"local [{self.source.tasks_dir}]"

    async def run_cycle(self) -> None:
        """Poll the source once; failures are isolated per local task file."""
        directories = _task_dirs(self.source.tasks_dir)
        _log.info("local task: %d task(s)", len(directories))
        for directory in directories:
            await self._ingest(directory)

    async def _ingest(self, directory: Path) -> None:
        """Start one valid task folder through shared ingestion protections."""
        root = Path(self.source.tasks_dir).resolve()
        ref = local_task_ref(directory, root)
        data = _read_local_task(directory)
        if data is None or not data.get("code_repo"):
            _log.info("ingest outcome=unresolved-repo %s", ref)
            return
        try:
            await self.ingestion.maybe_start_run(
                source="local-task",
                task_ref=ref,
                code_repo=data["code_repo"],
                base_branch=data.get("base_branch"),
            )
        except Exception:  # noqa: BLE001 — one task must not stop the rest
            _log.exception("local task: start failed for %s", ref)

    async def list_work_items(self) -> list[WorkItem]:
        """List every local task; starts no run."""
        items: list[WorkItem] = []
        root = Path(self.source.tasks_dir).resolve()
        for directory in _task_dirs(self.source.tasks_dir):
            data = _read_local_task(directory) or {}
            items.append(
                WorkItem(
                    source="local-task",
                    ref=local_task_ref(directory, root),
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
def get_local_task_poll_services() -> tuple[LocalTaskPollService, ...]:
    """Return one poll service per configured local task source."""
    return tuple(
        LocalTaskPollService(source, get_ingestion_service())
        for source in get_settings().local_sources()
    )

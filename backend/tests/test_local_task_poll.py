"""Tests for the local task poll ingestion cycle."""

from __future__ import annotations

import pytest

from app.config_models import TaskSourceConfig
from app.services.local_task_poll import LocalTaskPollService
from tests.local_task_helpers import write_local_task as _write_task

_TWO_CYCLES = 2


class _FakeIngestion:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def maybe_start_run(self, **kw):
        self.calls.append(kw)
        return "wf-x"

    async def observe_child_retrigger(self, task_ref, generation):
        self.calls.append({"retrigger": task_ref, "generation": generation})


def _source(tasks_dir) -> TaskSourceConfig:
    return TaskSourceConfig(
        type="local", tasks_dir=str(tasks_dir), code_host="local"
    )


@pytest.mark.asyncio
async def test_list_work_items_returns_one_per_file(tmp_path) -> None:
    """Ensure list_work_items surfaces every local task, starting no run."""
    _write_task(tmp_path, "hello-task")
    ingestion = _FakeIngestion()
    service = LocalTaskPollService(_source(tmp_path), ingestion)

    items = await service.list_work_items()

    assert len(items) == 1
    assert items[0].source == "local-task"
    assert items[0].ref == "local:hello-task"
    assert items[0].code_repo == "/tmp/sandbox.git"
    assert ingestion.calls == []


@pytest.mark.asyncio
async def test_run_cycle_ingests_each_local_task(tmp_path) -> None:
    """Ensure run_cycle calls maybe_start_run once per local task."""
    _write_task(tmp_path, "hello-task")
    ingestion = _FakeIngestion()
    service = LocalTaskPollService(_source(tmp_path), ingestion)

    await service.run_cycle()

    call = ingestion.calls[-1]
    assert call["source"] == "local-task"
    assert call["task_ref"] == "local:hello-task"
    assert call["code_repo"] == "/tmp/sandbox.git"


@pytest.mark.asyncio
async def test_run_cycle_twice_is_deduped_by_ingestion(tmp_path) -> None:
    """Ensure a second pass over the same file still calls maybe_start_run
    (dedup is the shared ingestion guard's job, not this service's)."""
    _write_task(tmp_path, "hello-task")
    ingestion = _FakeIngestion()
    service = LocalTaskPollService(_source(tmp_path), ingestion)

    await service.run_cycle()
    await service.run_cycle()

    assert len(ingestion.calls) == _TWO_CYCLES * 2
    assert {c["task_ref"] for c in ingestion.calls if "task_ref" in c} == {
        "local:hello-task"
    }


@pytest.mark.asyncio
async def test_generation_is_only_local_task_retrigger_signal(tmp_path) -> None:
    """An explicit local task generation reaches the child re-adoption seam."""
    _write_task(tmp_path, "hello-task", generation="2")
    ingestion = _FakeIngestion()

    await LocalTaskPollService(_source(tmp_path), ingestion).run_cycle()

    assert ingestion.calls[0] == {
        "retrigger": "local:hello-task",
        "generation": "2",
    }


@pytest.mark.asyncio
async def test_ingest_skips_local_task_missing_code_repo(tmp_path) -> None:
    """Ensure a local task without code_repo is skipped, not crashed on."""
    _write_task(tmp_path, "broken", code_repo="")
    ingestion = _FakeIngestion()
    await LocalTaskPollService(_source(tmp_path), ingestion).run_cycle()

    assert ingestion.calls == []

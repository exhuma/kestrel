"""Tests for the fixture poll ingestion cycle (feature 008)."""
from __future__ import annotations

import json

import pytest

from app.config_models import TaskSourceConfig
from app.services.fixture_poll import FixturePollService
from tests.conftest import _write_fixture_task as _write_fixture

_TWO_CYCLES = 2


class _FakeIngestion:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def maybe_start_run(self, **kw):
        self.calls.append(kw)
        return "wf-x"


def _source(fixtures_dir) -> TaskSourceConfig:
    return TaskSourceConfig(type="fixture", fixtures_dir=str(fixtures_dir))


@pytest.mark.asyncio
async def test_list_work_items_returns_one_per_file(tmp_path) -> None:
    """Ensure list_work_items surfaces every fixture file, starting no run."""
    _write_fixture(tmp_path, "hello-fixture")
    ingestion = _FakeIngestion()
    service = FixturePollService(_source(tmp_path), ingestion)

    items = await service.list_work_items()

    assert len(items) == 1
    assert items[0].source == "fixture-issue"
    assert items[0].ref == "fixture:hello-fixture"
    assert items[0].code_repo == "me/sandbox"
    assert ingestion.calls == []


@pytest.mark.asyncio
async def test_run_cycle_ingests_each_fixture(tmp_path) -> None:
    """Ensure run_cycle calls maybe_start_run once per fixture file."""
    _write_fixture(tmp_path, "hello-fixture")
    ingestion = _FakeIngestion()
    service = FixturePollService(_source(tmp_path), ingestion)

    await service.run_cycle()

    assert len(ingestion.calls) == 1
    call = ingestion.calls[0]
    assert call["source"] == "fixture-issue"
    assert call["task_ref"] == "fixture:hello-fixture"
    assert call["code_repo"] == "me/sandbox"


@pytest.mark.asyncio
async def test_run_cycle_twice_is_deduped_by_ingestion(tmp_path) -> None:
    """Ensure a second pass over the same file still calls maybe_start_run
    (dedup is the shared ingestion guard's job, not this service's)."""
    _write_fixture(tmp_path, "hello-fixture")
    ingestion = _FakeIngestion()
    service = FixturePollService(_source(tmp_path), ingestion)

    await service.run_cycle()
    await service.run_cycle()

    assert len(ingestion.calls) == _TWO_CYCLES
    assert {c["task_ref"] for c in ingestion.calls} == {
        "fixture:hello-fixture"
    }


@pytest.mark.asyncio
async def test_ingest_skips_fixture_missing_code_repo(tmp_path) -> None:
    """Ensure a fixture file without code_repo is skipped, not crashed on."""
    (tmp_path / "broken.json").write_text(
        json.dumps({"title": "t", "body": "b"})
    )
    ingestion = _FakeIngestion()
    service = FixturePollService(_source(tmp_path), ingestion)

    await service.run_cycle()

    assert ingestion.calls == []

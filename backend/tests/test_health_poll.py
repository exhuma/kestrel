"""Tests for HealthPollService (feature 014)."""
from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.services import health as health_module
from app.services.health import HealthPollService, HealthState


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch) -> None:
    """Give every test a short, deterministic timeout/interval instead of
    the real defaults, without needing a full app settings fixture."""
    monkeypatch.setattr(
        health_module, "get_settings",
        lambda: _settings(
            health_check_timeout_seconds=1, health_check_interval_seconds=0
        ),
    )


@pytest.mark.asyncio
async def test_run_cycle_checks_every_entry_and_updates_the_store() -> None:
    """Ensure a cycle runs every registered check and records the
    outcome."""
    calls: list[str] = []

    async def ok() -> bool:
        calls.append("ok")
        return True

    async def bad() -> bool:
        calls.append("bad")
        return False

    svc = HealthPollService([("ok", ok), ("bad", bad)])
    await svc.run_cycle()

    assert calls == ["ok", "bad"]
    assert svc.store.get("ok").state == HealthState.HEALTHY
    assert svc.store.get("bad").state == HealthState.UNHEALTHY


@pytest.mark.asyncio
async def test_run_cycle_treats_a_raised_exception_as_unhealthy() -> None:
    """Ensure a misbehaving check (one that raises anyway) is contained,
    not propagated."""

    async def broken() -> bool:
        raise RuntimeError("boom")

    svc = HealthPollService([("broken", broken)])
    await svc.run_cycle()

    assert svc.store.get("broken").state == HealthState.UNHEALTHY


@pytest.mark.asyncio
async def test_a_hanging_check_is_bounded_and_does_not_block_the_rest() -> None:
    """Ensure one unresponsive entry is timed out and the next entry in
    the same cycle still runs (spec.md edge case, research.md R3)."""

    async def hangs() -> bool:
        await asyncio.sleep(10)
        return True

    async def fast() -> bool:
        return True

    svc = HealthPollService([("hangs", hangs), ("fast", fast)])
    await asyncio.wait_for(svc.run_cycle(), timeout=3)

    assert svc.store.get("hangs").state == HealthState.UNHEALTHY
    assert svc.store.get("fast").state == HealthState.HEALTHY


@pytest.mark.asyncio
async def test_run_cycle_publishes_one_bus_tick() -> None:
    """Ensure a completed cycle notifies subscribers exactly once."""

    async def ok() -> bool:
        return True

    svc = HealthPollService([("ok", ok)])
    q = svc.bus.subscribe()
    await svc.run_cycle()

    assert q.qsize() == 1


@pytest.mark.asyncio
async def test_refresh_returns_false_for_an_unregistered_name() -> None:
    """Ensure refreshing an unknown name is a clean no-op (FR-004's HTTP
    404 is the router's own concern — this is the service-level guard)."""
    svc = HealthPollService([])
    assert await svc.refresh("does-not-exist") is False


@pytest.mark.asyncio
async def test_refresh_checks_and_publishes() -> None:
    """Ensure a successful refresh updates the store and ticks the bus."""

    async def ok() -> bool:
        return True

    svc = HealthPollService([("github", ok)])
    q = svc.bus.subscribe()

    assert await svc.refresh("github") is True

    assert svc.store.get("github").state == HealthState.HEALTHY
    assert q.qsize() == 1


@pytest.mark.asyncio
async def test_refresh_does_not_duplicate_a_check_already_in_flight() -> None:
    """Ensure a refresh racing an in-flight check (background cycle or
    another refresh) for the same entry does not start a second,
    redundant check (FR-005, research.md R7)."""
    calls = 0
    release = asyncio.Event()

    async def slow() -> bool:
        nonlocal calls
        calls += 1
        await release.wait()
        return True

    svc = HealthPollService([("github", slow)])
    first = asyncio.create_task(svc.refresh("github"))
    await asyncio.sleep(0)  # let `first` acquire the lock and start `slow`

    second = asyncio.create_task(svc.refresh("github"))
    await asyncio.sleep(0)  # let `second` observe the lock already held

    release.set()
    await asyncio.gather(first, second)

    assert calls == 1


@pytest.mark.asyncio
async def test_list_work_items_is_always_empty() -> None:
    """No dry-run listing — required by the PollSource protocol."""
    svc = HealthPollService([])
    assert await svc.list_work_items() == []


@pytest.mark.asyncio
async def test_name_property_is_health() -> None:
    """Display label for the poll dry-run listing."""
    assert HealthPollService([]).name == "health"

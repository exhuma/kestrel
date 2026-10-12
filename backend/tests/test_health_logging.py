"""An unreachable source says why in the log (health checks, 2026-10-12).

The health status the UI shows stays binary (feature 014); the reason goes
to the server log, once per change rather than every cycle.
"""
from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from app.config import Settings
from app.services import health as health_module
from app.services.health import HealthPollService, HealthState

#: The health check timeout the tests run with, in seconds.
TIMEOUT_SECONDS = 1
#: Longer than any reason the log keeps.
LONG_BODY = "x" * 5000
#: The most characters a logged reason may have (with some headroom).
MAX_REASON = 600


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        health_module, "get_settings",
        lambda: Settings(
            _env_file=None,
            health_check_timeout_seconds=TIMEOUT_SECONDS,
            health_check_interval_seconds=0,
        ),
    )


class _Check:
    """A check whose outcome each test sets: raise, return False, or ok."""

    def __init__(self) -> None:
        self.error: BaseException | None = None
        self.healthy = True

    async def __call__(self) -> bool:
        if self.error is not None:
            raise self.error
        return self.healthy


def _connect_error(message: str) -> httpx.ConnectError:
    return httpx.ConnectError(
        message, request=httpx.Request("GET", "https://jira.example/myself")
    )


def _records(caplog: pytest.LogCaptureFixture, level: int) -> list:
    return [
        r for r in caplog.records
        if r.name == "kestrel.health" and r.levelno == level
    ]


@pytest.mark.asyncio
async def test_the_first_failure_logs_the_reason_and_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    check = _Check()
    check.error = _connect_error("[SSL: CERTIFICATE_VERIFY_FAILED]")
    svc = HealthPollService([("jira", check)])

    with caplog.at_level(logging.DEBUG, logger="kestrel.health"):
        await svc.run_cycle()

    (warning,) = _records(caplog, logging.WARNING)
    assert warning.getMessage() == (
        "health: jira unreachable: ConnectError: "
        "[SSL: CERTIFICATE_VERIFY_FAILED]"
    )
    assert warning.exc_info is not None
    assert svc.store.get("jira").state == HealthState.UNHEALTHY


@pytest.mark.asyncio
async def test_the_same_failure_again_is_not_repeated_above_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    check = _Check()
    check.error = _connect_error("connection refused")
    svc = HealthPollService([("jira", check)])
    await svc.run_cycle()

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="kestrel.health"):
        await svc.run_cycle()

    assert not _records(caplog, logging.WARNING)
    assert _records(caplog, logging.DEBUG)
    assert svc.store.get("jira").state == HealthState.UNHEALTHY


@pytest.mark.asyncio
async def test_a_changed_reason_is_logged_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    check = _Check()
    check.error = _connect_error("connection refused")
    svc = HealthPollService([("jira", check)])
    await svc.run_cycle()
    check.error = _connect_error("name resolution failed")

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="kestrel.health"):
        await svc.run_cycle()

    (warning,) = _records(caplog, logging.WARNING)
    assert "name resolution failed" in warning.getMessage()


@pytest.mark.asyncio
async def test_recovery_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    check = _Check()
    check.error = _connect_error("connection refused")
    svc = HealthPollService([("gitlab", check)])
    await svc.run_cycle()
    check.error = None

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="kestrel.health"):
        await svc.run_cycle()

    (info,) = _records(caplog, logging.INFO)
    assert info.getMessage() == "health: gitlab reachable again"
    assert svc.store.get("gitlab").state == HealthState.HEALTHY


@pytest.mark.asyncio
async def test_a_timeout_says_how_long_it_waited(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def hangs() -> bool:
        await asyncio.sleep(10)
        return True

    svc = HealthPollService([("jira", hangs)])
    with caplog.at_level(logging.DEBUG, logger="kestrel.health"):
        await svc.run_cycle()

    (warning,) = _records(caplog, logging.WARNING)
    assert warning.getMessage() == (
        f"health: jira unreachable: timed out after {TIMEOUT_SECONDS} s"
    )


@pytest.mark.asyncio
async def test_a_long_error_body_is_truncated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    check = _Check()
    check.error = RuntimeError(f"GET /myself -> 502: {LONG_BODY}")
    svc = HealthPollService([("jira", check)])

    with caplog.at_level(logging.DEBUG, logger="kestrel.health"):
        await svc.run_cycle()

    (warning,) = _records(caplog, logging.WARNING)
    assert "GET /myself -> 502" in warning.getMessage()
    assert len(warning.getMessage()) < MAX_REASON


@pytest.mark.asyncio
async def test_a_plain_false_is_logged_without_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    check = _Check()
    check.healthy = False
    svc = HealthPollService([("local", check)])

    with caplog.at_level(logging.DEBUG, logger="kestrel.health"):
        await svc.run_cycle()

    (warning,) = _records(caplog, logging.WARNING)
    assert warning.getMessage() == (
        "health: local unreachable: reported unhealthy (no detail)"
    )

"""Tests for bounded provider rate-limit retries."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.backends.rate_limit import retry_rate_limited

_RETRIES = 2
_ATTEMPTS = _RETRIES + 1
_BACKOFF_SECONDS = 2.0


def _rate_limit_error(
    headers: dict[str, str] | None = None,
) -> httpx.HTTPStatusError:
    """Build an HTTP 429 error with optional provider response headers."""
    request = httpx.Request("POST", "http://provider.local/message")
    response = httpx.Response(429, headers=headers, request=request)
    return httpx.HTTPStatusError(
        "rate limited", request=request, response=response
    )


@pytest.mark.asyncio
async def test_rate_limit_retries_using_retry_after(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure a 429 waits for its Retry-After value before retrying."""
    calls = 0
    waits: list[float] = []

    async def sleep(delay: float) -> None:
        """Record the requested retry delay without waiting in the test."""
        waits.append(delay)

    async def send() -> object:
        """Fail once with Retry-After, then succeed."""
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _rate_limit_error({"Retry-After": "2"})
        return {"ok": True}

    monkeypatch.setattr(asyncio, "sleep", sleep)
    assert await retry_rate_limited(send, _RETRIES, _BACKOFF_SECONDS) == {
        "ok": True
    }
    assert calls == _RETRIES
    assert waits == [_BACKOFF_SECONDS]
    assert "retry 1 of 2 in 2.0s (Retry-After" in caplog.text


@pytest.mark.asyncio
async def test_rate_limit_uses_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure a 429 without Retry-After uses exponential base delays."""
    calls = 0
    waits: list[float] = []

    async def sleep(delay: float) -> None:
        """Record retry delays without waiting in the test."""
        waits.append(delay)

    async def send() -> object:
        """Fail twice without Retry-After, then succeed."""
        nonlocal calls
        calls += 1
        if calls < _ATTEMPTS:
            raise _rate_limit_error()
        return {"ok": True}

    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr("app.backends.rate_limit.random.uniform", lambda *_: 0)
    assert await retry_rate_limited(send, _RETRIES, _BACKOFF_SECONDS) == {
        "ok": True
    }
    assert calls == _ATTEMPTS
    assert waits == [_BACKOFF_SECONDS, _BACKOFF_SECONDS * _RETRIES]
    assert "exponential backoff; base 2.0s" in caplog.text


@pytest.mark.asyncio
async def test_rate_limit_failure_reports_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure persistent rate limiting fails after the configured retries."""
    calls = 0

    async def sleep(delay: float) -> None:
        """Avoid waiting while testing failed retries."""
        del delay

    async def send() -> object:
        """Always report provider rate limiting."""
        nonlocal calls
        calls += 1
        raise _rate_limit_error()

    monkeypatch.setattr(asyncio, "sleep", sleep)
    with pytest.raises(RuntimeError, match="rate limit"):
        await retry_rate_limited(send, _RETRIES, _BACKOFF_SECONDS)
    assert calls == _ATTEMPTS
    assert "persisted after 2 retries" in caplog.text


@pytest.mark.asyncio
async def test_non_rate_limit_errors_are_not_retried() -> None:
    """Ensure server errors retain the existing immediate-failure behavior."""
    calls = 0
    request = httpx.Request("POST", "http://provider.local/message")
    response = httpx.Response(500, request=request)
    error = httpx.HTTPStatusError("failed", request=request, response=response)

    async def send() -> object:
        """Always report a server error unrelated to rate limiting."""
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(httpx.HTTPStatusError):
        await retry_rate_limited(send, _RETRIES, _BACKOFF_SECONDS)
    assert calls == 1

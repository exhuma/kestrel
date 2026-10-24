"""Bounded retry policy for provider rate-limit responses."""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

import httpx

_RATE_LIMIT_STATUS = 429
_logger = logging.getLogger(__name__)


def _retry_after_seconds(value: str | None) -> float | None:
    """Parse a positive Retry-After value in seconds, if one is usable."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def _retry_delay(
    response: httpx.Response, retry: int, base: float
) -> tuple[float, str]:
    """Return the delay and its source for one rate-limit retry."""
    retry_after = _retry_after_seconds(response.headers.get("retry-after"))
    if retry_after is not None:
        return retry_after, "Retry-After"
    delay = base * (2 ** retry)
    return delay + random.uniform(0, base / 2), "exponential backoff"


async def retry_rate_limited(
    send: Callable[[], Awaitable[object]], retries: int, backoff_seconds: float
) -> object:
    """Call ``send``, retrying HTTP 429 responses up to ``retries`` times."""
    for retry in range(retries + 1):
        try:
            return await send()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != _RATE_LIMIT_STATUS:
                raise
            if retry == retries:
                _logger.error(
                    "provider rate limit persisted after %s retries", retries
                )
                raise RuntimeError(
                    f"provider rate limit persisted after {retries} retries"
                ) from exc
            delay, source = _retry_delay(exc.response, retry, backoff_seconds)
            _logger.warning(
                "provider rate-limited request; retry %s of %s in %.1fs "
                "(%s; base %.1fs)",
                retry + 1,
                retries,
                delay,
                source,
                backoff_seconds,
            )
            await asyncio.sleep(delay)
    raise AssertionError("rate-limit retry loop must return or raise")

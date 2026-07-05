"""Tests for the cross-cutting HTTP middleware stack.

Covers the module-http-middleware-hardening contract: security headers,
version header, and correlation-ID honour/generate/echo on every response.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app.logging_config import CorrelationIDFilter, get_correlation_id
from app.main import create_app


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_every_response_carries_security_and_version_headers() -> None:
    """Ensure the three security headers and the version header are set."""
    app = create_app()
    async with _client(app) as client:
        resp = await client.get("/healthz")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert (
        resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    )
    # Baked via KESTREL_VERSION; defaults to the from-source sentinel.
    assert resp.headers["x-kestrel-version"] == "0.0.0-dev"


@pytest.mark.asyncio
async def test_correlation_id_is_generated_when_absent() -> None:
    """Ensure a response gets a fresh correlation ID when none is sent."""
    app = create_app()
    async with _client(app) as client:
        resp = await client.get("/healthz")
    assert resp.headers.get("x-correlation-id")


@pytest.mark.asyncio
async def test_inbound_correlation_id_is_preserved() -> None:
    """Ensure an inbound X-Correlation-ID is echoed unchanged."""
    app = create_app()
    async with _client(app) as client:
        resp = await client.get(
            "/healthz", headers={"X-Correlation-ID": "trace-abc-123"}
        )
    assert resp.headers["x-correlation-id"] == "trace-abc-123"


@pytest.mark.asyncio
async def test_correlation_id_does_not_leak_between_requests() -> None:
    """Ensure the correlation context is cleared after each request."""
    app = create_app()
    async with _client(app) as client:
        await client.get(
            "/healthz", headers={"X-Correlation-ID": "trace-abc-123"}
        )
    # Back on the test's own context, nothing should remain bound.
    assert get_correlation_id() is None


def test_correlation_filter_stamps_records() -> None:
    """Ensure the filter always provides a correlation_id attribute."""
    record = logging.LogRecord(
        "app.test", logging.INFO, __file__, 1, "hi", None, None
    )
    assert CorrelationIDFilter().filter(record) is True
    assert record.correlation_id == "-"

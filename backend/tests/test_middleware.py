"""Tests for the cross-cutting HTTP middleware stack.

Covers the module-http-middleware-hardening (v2) contract: three security
headers and a version header on every response, one structured log line per
request, and — deliberately — **no** custom correlation header (correlation
rides W3C trace context via OpenTelemetry).
"""
from __future__ import annotations

import logging

import httpx
import pytest

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
async def test_no_correlation_header_is_emitted() -> None:
    """Ensure the v2 middleware adds no bespoke correlation header.

    Cross-request correlation is W3C trace context (``traceparent``), owned by
    module-opentelemetry — not a hand-rolled ``X-Correlation-ID``.
    """
    app = create_app()
    async with _client(app) as client:
        resp = await client.get("/healthz")
    assert "x-correlation-id" not in resp.headers


@pytest.mark.asyncio
async def test_inbound_correlation_header_is_not_echoed() -> None:
    """Ensure an inbound X-Correlation-ID is ignored, not reflected."""
    app = create_app()
    async with _client(app) as client:
        resp = await client.get(
            "/healthz", headers={"X-Correlation-ID": "trace-abc-123"}
        )
    assert "x-correlation-id" not in resp.headers


@pytest.mark.asyncio
async def test_request_emits_one_structured_log_line(caplog) -> None:
    """Ensure each request logs exactly one method/path/status/duration line."""
    app = create_app()
    with caplog.at_level(logging.INFO, logger="app.middleware"):
        async with _client(app) as client:
            await client.get("/livez")
    lines = [
        r for r in caplog.records if r.name == "app.middleware"
    ]
    assert len(lines) == 1
    message = lines[0].getMessage()
    assert "GET /livez" in message
    assert "-> 200" in message

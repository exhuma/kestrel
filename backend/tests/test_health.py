"""Tests for the health-probe helpers and endpoints.

Covers the module-observability-healthz contract: three probes with distinct
semantics, the compact schema, aggregation, and the 200/503 mapping.
"""
from __future__ import annotations

import httpx
import pytest

from app.health import (
    build_response,
    overall_status,
    status_code,
)
from app.main import create_app


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _component(status: str, *, required: bool = True) -> dict:
    return {
        "name": "database",
        "kind": "database",
        "required": required,
        "status": status,
        "reason_code": "ok" if status == "ok" else "x",
    }


def test_required_failure_forces_fail() -> None:
    """Ensure a failed required dependency makes the probe fail."""
    assert overall_status([_component("fail")], include_optional=False) == (
        "fail"
    )
    assert overall_status([_component("unknown")], include_optional=True) == (
        "fail"
    )


def test_optional_failure_only_degrades_when_included() -> None:
    """Ensure a bad optional dependency degrades healthz, not readyz."""
    comps = [_component("ok"), _component("fail", required=False)]
    assert overall_status(comps, include_optional=True) == "degraded"
    assert overall_status(comps, include_optional=False) == "ok"


def test_status_code_mapping() -> None:
    """Ensure only fail maps to 503."""
    assert status_code("ok") == 200
    assert status_code("degraded") == 200
    assert status_code("fail") == 503


def test_build_response_shape() -> None:
    """Ensure the payload carries probe, status, checked_at, components."""
    payload = build_response("livez", [], "ok")
    assert payload["probe"] == "livez"
    assert payload["status"] == "ok"
    assert payload["components"] == []
    assert "checked_at" in payload


@pytest.mark.asyncio
async def test_livez_is_ok_without_touching_the_database() -> None:
    """Ensure /livez reports ok with no dependency components."""
    app = create_app()
    async with _client(app) as client:
        resp = await client.get("/livez")
    assert resp.status_code == 200
    body = resp.json()
    assert body["probe"] == "livez"
    assert body["status"] == "ok"
    assert body["components"] == []


@pytest.mark.asyncio
async def test_readyz_ok_when_database_reachable() -> None:
    """Ensure /readyz reports ok and lists the database component."""
    app = create_app()
    async with _client(app) as client:
        resp = await client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["probe"] == "readyz"
    assert body["status"] == "ok"
    assert body["components"][0]["kind"] == "database"


@pytest.mark.asyncio
async def test_readyz_returns_503_when_database_unreachable(
    monkeypatch,
) -> None:
    """Ensure /readyz fails with 503 when the DB probe reports fail."""
    from app import health

    async def _broken(_engine) -> dict:
        return {
            "name": "database",
            "kind": "database",
            "required": True,
            "status": "fail",
            "reason_code": "db_unreachable",
        }

    monkeypatch.setattr(health, "check_database", _broken)
    app = create_app()
    async with _client(app) as client:
        resp = await client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "fail"
    assert body["components"][0]["reason_code"] == "db_unreachable"


@pytest.mark.asyncio
async def test_check_database_reports_unknown_on_timeout(monkeypatch) -> None:
    """Ensure a probe slower than the bound reports unknown, not fail."""
    import time

    from app import health

    class _SlowConn:
        def __enter__(self) -> "_SlowConn":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def execute(self, *args: object) -> None:
            pass

    class _SlowEngine:
        def connect(self) -> "_SlowConn":
            time.sleep(0.5)  # exceeds the (patched) bound
            return _SlowConn()

    monkeypatch.setattr(health, "DB_CHECK_TIMEOUT_SECONDS", 0.05)
    component = await health.check_database(_SlowEngine())
    assert component["status"] == "unknown"
    assert component["reason_code"] == "timeout"
    # A required dependency that is unknown gates readiness out.
    assert health.overall_status([component], include_optional=False) == "fail"

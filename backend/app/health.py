"""Health-probe evaluation (see module-observability-healthz).

Pure helpers that build the compact ``HealthResponse`` payload, aggregate
component statuses, and map the result to an HTTP status code. Route wiring
lives in :mod:`app.main`.

Payloads deliberately expose no attacker-useful internals — no versions,
connection strings, hostnames, or raw error text — only a component name,
kind, and a stable, generic ``reason_code``.
"""
from __future__ import annotations

import datetime as _dt
import time
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

Status = Literal["ok", "degraded", "fail", "unknown"]
Probe = Literal["livez", "readyz", "healthz"]

#: Statuses that make a dependency count as "bad" during aggregation.
_BAD = ("fail", "unknown")


def _now() -> str:
    """Return an RFC3339 UTC timestamp for ``checked_at``."""
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def check_database(engine: Engine) -> dict[str, Any]:
    """Probe the database with a cheap ``SELECT 1``; never raises.

    :returns: A component dict; ``fail`` with a generic ``reason_code`` if the
        database cannot be reached, otherwise ``ok`` with a rounded latency.
    """
    start = time.monotonic()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return {
            "name": "database",
            "kind": "database",
            "required": True,
            "status": "fail",
            "reason_code": "db_unreachable",
        }
    return {
        "name": "database",
        "kind": "database",
        "required": True,
        "status": "ok",
        "reason_code": "ok",
        "latency_ms": round((time.monotonic() - start) * 1000),
    }


def overall_status(
    components: list[dict[str, Any]], *, include_optional: bool
) -> Status:
    """Aggregate component statuses per the kit's rules.

    Any required dependency in ``fail``/``unknown`` makes the whole probe
    ``fail``. When ``include_optional`` is set (``/healthz``), a bad optional
    dependency degrades the probe rather than failing it.
    """
    if any(c["required"] and c["status"] in _BAD for c in components):
        return "fail"
    if include_optional and any(
        not c["required"] and c["status"] in _BAD for c in components
    ):
        return "degraded"
    return "ok"


def status_code(status: Status) -> int:
    """Map a probe status to its HTTP code: ``fail`` -> 503, else 200."""
    return 503 if status == "fail" else 200


def build_response(
    probe: Probe, components: list[dict[str, Any]], status: Status
) -> dict[str, Any]:
    """Assemble a ``HealthResponse`` payload."""
    return {
        "probe": probe,
        "status": status,
        "checked_at": _now(),
        "components": components,
    }

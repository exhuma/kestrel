"""Health-probe evaluation (see module-observability-healthz).

Pure helpers that build the compact ``HealthResponse`` payload, aggregate
component statuses, and map the result to an HTTP status code. Route wiring
lives in :mod:`app.main`.

Payloads deliberately expose no attacker-useful internals — no versions,
connection strings, hostnames, or raw error text — only a component name,
kind, and a stable, generic ``reason_code``.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import time
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

Status = Literal["ok", "degraded", "fail", "unknown"]
Probe = Literal["livez", "readyz", "healthz"]

#: Statuses that make a dependency count as "bad" during aggregation.
_BAD = ("fail", "unknown")

#: Upper bound on a single dependency probe. A check that exceeds this
#: reports ``unknown`` rather than ``fail`` — a slow dependency is not proof
#: of a dead one — and the check is run off the event loop so a hung probe
#: can never block the process or amplify an outage.
DB_CHECK_TIMEOUT_SECONDS = 2.0


def _now() -> str:
    """Return an RFC3339 UTC timestamp for ``checked_at``."""
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _db_component(
    status: Status, reason_code: str, *, latency_ms: int | None = None
) -> dict[str, Any]:
    """Build the ``database`` component dict for a health payload."""
    component: dict[str, Any] = {
        "name": "database",
        "kind": "database",
        "required": True,
        "status": status,
        "reason_code": reason_code,
    }
    if latency_ms is not None:
        component["latency_ms"] = latency_ms
    return component


async def check_database(engine: Engine) -> dict[str, Any]:
    """Probe the database with a bounded, cheap ``SELECT 1``; never raises.

    The blocking probe runs in a worker thread and is capped at
    :data:`DB_CHECK_TIMEOUT_SECONDS`, so it neither blocks the event loop nor
    hangs the probe. A timeout reports ``unknown`` (the dependency is
    unconfirmed, not proven dead); any other error reports ``fail``.

    :param engine: The SQLAlchemy engine to probe.
    :returns: A ``database`` component dict for the health payload.
    """

    def _probe() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    start = time.monotonic()
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_probe), DB_CHECK_TIMEOUT_SECONDS
        )
    except TimeoutError:
        return _db_component("unknown", "timeout")
    except Exception:
        return _db_component("fail", "db_unreachable")
    latency_ms = round((time.monotonic() - start) * 1000)
    return _db_component("ok", "ok", latency_ms=latency_ms)


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

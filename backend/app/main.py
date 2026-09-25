"""FastAPI application factory for kestrel."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.middleware import (
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    VersionHeaderMiddleware,
)
from app.services.exceptions import (
    DirectPromptTooLargeError,
    SessionNotFoundError,
    SessionStartError,
    UnconfirmedDirectPromptError,
)

# Unified logging (see app.logging_config) configures the root logger, so a
# plain module logger surfaces on the same stream as uvicorn's own output.
_logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Report the backend configuration, then recover persisted runs."""
    from app.backends.registry import get_backend_registry
    from app.config import get_settings
    from app.logging_config import configure_logging

    settings = get_settings()
    # Apply unified logging here, at startup, so it survives however the app
    # was launched. Uvicorn configures its own logging before the lifespan
    # runs (leaving the root logger handler-less on the `uvicorn app.main:app`
    # path); reconfiguring now routes app + uvicorn logs through one handler
    # and makes KESTREL_LOG_LEVEL/KESTREL_LOG_FORMAT authoritative.
    configure_logging(settings.log_level, settings.log_format)
    # Building the registry now fails fast on a misconfigured default and
    # makes the effective config visible in the logs — the first thing to
    # check when a session runs on the wrong backend.
    get_backend_registry()
    _logger.info(
        "config file: %s | backends: %s | ad-hoc sessions dispatch to: %r",
        settings.config_file or settings.backends_file or "(none)",
        {c.id: c.type for c in settings.backends},
        settings.default_session_backend,
    )

    # Board specialist roster (feature 026, FR-009): a missing, malformed,
    # or incomplete roster must block startup before any task can be
    # ingested, not fail later on first dispatch. Only ids are logged —
    # never prompt content.
    from app.services.board.bootstrap import get_specialist_roster

    roster = get_specialist_roster()
    _logger.info("board specialists loaded: %s", sorted(roster.ids()))

    # Operator-hooks audit trail (feature 006, FR-016): log what's found in
    # each configured hooks_dir, so an operator has a chance to notice a
    # script they didn't expect — a nudge, not an access control (a hook
    # inherits kestrel's full environment, see docs/hooks.md).
    from app.services.hooks import audit_hooks_dir

    for source in settings.task_sources:
        audit_hooks_dir(source.hooks_dir)

    # Source poll loops (features 002/003/004): one background loop per
    # configured task source — the GitHub reconcile backstop and the Jira poll
    # (its sole transport). Each runs an initial cycle promptly, then every
    # ``poll_interval_seconds``. All are cancelled on shutdown.
    from app.services.poll_source import configured_poll_sources

    poll_tasks = [
        asyncio.create_task(src.run_forever())
        for src in configured_poll_sources(settings)
    ]

    # Board claim-expiry recovery (feature 026, FR-004/FR-012): runs
    # unconditionally alongside the poll loops above, since it recovers
    # abandoned specialist claims rather than polling any task source.
    from app.services.board.bootstrap import (
        get_ci_poll_service,
        get_recovery_service,
    )

    poll_tasks.append(asyncio.create_task(get_recovery_service().run_forever()))

    # Board required-CI polling (feature 026, T052): also runs
    # unconditionally — a workflow with no required_ci_statuses configured
    # for its source/repo is simply never eligible, so this is a no-op
    # sweep for a deployment that hasn't configured any.
    poll_tasks.append(asyncio.create_task(get_ci_poll_service().run_forever()))

    try:
        yield
    finally:
        for task in poll_tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def _register_exception_handlers(app: FastAPI) -> None:
    """Map domain exceptions crossing the service -> router boundary to HTTP."""

    @app.exception_handler(SessionNotFoundError)
    async def _session_not_found(
        request: Request, exc: SessionNotFoundError
    ) -> JSONResponse:
        """Map an unknown session to HTTP 404."""
        return JSONResponse(
            status_code=404, content={"detail": "unknown session"}
        )

    @app.exception_handler(SessionStartError)
    async def _session_start_failed(
        request: Request, exc: SessionStartError
    ) -> JSONResponse:
        """Map a failed session start to HTTP 502."""
        return JSONResponse(
            status_code=502, content={"detail": "session start failed"}
        )

    @app.exception_handler(UnconfirmedDirectPromptError)
    async def _unconfirmed_direct_prompt(
        request: Request, exc: UnconfirmedDirectPromptError
    ) -> JSONResponse:
        """Map a missing injection-risk confirmation to HTTP 400."""
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(DirectPromptTooLargeError)
    async def _direct_prompt_too_large(
        request: Request, exc: DirectPromptTooLargeError
    ) -> JSONResponse:
        """Map an oversized direct prompt to HTTP 413."""
        return JSONResponse(status_code=413, content={"detail": str(exc)})


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    from app.config import get_settings

    app = FastAPI(
        title="kestrel", version=get_settings().version, lifespan=_lifespan
    )

    _register_exception_handlers(app)

    # Cross-cutting HTTP middleware (see module-http-middleware-hardening).
    # ORDER MATTERS: Starlette applies middleware LIFO, so the LAST
    # add_middleware call sits OUTERMOST and runs first on the way in. Keep
    # CORS last so it answers preflight OPTIONS before any inner layer; keep
    # request logging inside it so the log line reflects the real handler.
    # Do not reorder. (Rate limiting is intentionally omitted: single-user
    # localhost tool — add a limiter here if ever exposed beyond loopback.)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(VersionHeaderMiddleware, version=get_settings().version)
    app.add_middleware(RequestLoggingMiddleware)
    # Personal single-user dev tool: allow the SPA from any local port
    # (Vite may pick 5173, 5174, ... depending on what is free) served
    # from any loopback host (localhost, 127.0.0.1, or IPv6 ::1) — the
    # browser treats these as distinct origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1|\[::1\]):\d+",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health probes (see module-observability-healthz). The running version
    # rides the X-Kestrel-Version response header (VersionHeaderMiddleware),
    # not the body — health payloads must not leak version fingerprints.
    from app.health import (
        build_response,
        check_database,
        overall_status,
        status_code,
    )

    @app.get("/livez")
    async def livez() -> JSONResponse:
        """Liveness: the process is up. Touches no external dependency."""
        return JSONResponse(build_response("livez", [], "ok"))

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        """Readiness: required dependencies (the database) are usable.

        Returns HTTP 503 when the database is unreachable so an unready
        container is gated out of traffic rather than served.
        """
        from app.persistence.db import get_engine

        components = [await check_database(get_engine())]
        status = overall_status(components, include_optional=False)
        return JSONResponse(
            build_response("readyz", components, status),
            status_code=status_code(status),
        )

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        """Operational summary over required and optional dependencies."""
        from app.persistence.db import get_engine

        components = [await check_database(get_engine())]
        status = overall_status(components, include_optional=True)
        return JSONResponse(
            build_response("healthz", components, status),
            status_code=status_code(status),
        )

    from app.routers import (
        board,
        github_webhook,
        health,
        identity,
        notifications,
        sessions,
    )

    app.include_router(sessions.router)
    app.include_router(board.router)
    app.include_router(notifications.router)
    app.include_router(health.router)
    app.include_router(identity.router)
    app.include_router(github_webhook.router)
    if get_settings().board_dev_actions_enabled:
        # Temporary, dev-only (T069) — see board_dev.py's module docstring.
        from app.routers import board_dev

        app.include_router(board_dev.router)

    # OpenTelemetry tracing (see app.telemetry, module-opentelemetry). A no-op
    # unless KESTREL_OTEL_ENABLED: instruments the app + logging so spans and
    # trace-linked log fields flow when a collector is configured.
    from app import telemetry

    telemetry.init_tracing(app, get_settings())

    # When packaged as a single image the backend also serves the built SPA.
    # Mounted last so the API routers above keep priority; html=True serves
    # index.html for unknown paths, giving the SPA its client-side routing.
    static_dir = get_settings().static_dir
    if static_dir and os.path.isdir(static_dir):
        from fastapi.staticfiles import StaticFiles

        app.mount(
            "/", StaticFiles(directory=static_dir, html=True), name="spa"
        )

    return app


app = create_app()

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
from app.questionnaire import AnswerValidationError
from app.services.exceptions import (
    InvalidWorkflowStateError,
    SessionNotFoundError,
    SessionStartError,
    WorkflowNotFoundError,
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
    from app.services.workflows import get_workflow_service

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
        "backends: %s | ad-hoc sessions dispatch to: %r",
        {c.id: c.type for c in settings.backends},
        settings.default_session_backend,
    )

    await get_workflow_service().recover()

    # Poll reconciliation (feature 002, US2): a safety net for missed webhook
    # deliveries. Only started when repos are configured to watch; runs an
    # initial cycle promptly, then every interval. Cancelled on shutdown.
    reconcile_task: asyncio.Task | None = None
    if settings.watched_repos:
        from app.services.reconcile import get_reconcile_service

        reconcile_task = asyncio.create_task(
            get_reconcile_service().run_forever()
        )

    try:
        yield
    finally:
        if reconcile_task is not None:
            reconcile_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reconcile_task


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    from app.config import get_settings

    app = FastAPI(
        title="kestrel", version=get_settings().version, lifespan=_lifespan
    )

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

    @app.exception_handler(WorkflowNotFoundError)
    async def _workflow_not_found(
        request: Request, exc: WorkflowNotFoundError
    ) -> JSONResponse:
        """Map an unknown workflow to HTTP 404."""
        return JSONResponse(
            status_code=404, content={"detail": "unknown workflow"}
        )

    @app.exception_handler(InvalidWorkflowStateError)
    async def _invalid_workflow_state(
        request: Request, exc: InvalidWorkflowStateError
    ) -> JSONResponse:
        """Map an invalid workflow transition to HTTP 409."""
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(AnswerValidationError)
    async def _invalid_answers(
        request: Request, exc: AnswerValidationError
    ) -> JSONResponse:
        """Map invalid questionnaire answers to HTTP 422."""
        return JSONResponse(
            status_code=422,
            content={
                "detail": "invalid answers",
                "errors": exc.errors,
            },
        )

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
        github_webhook,
        notifications,
        sessions,
        workflows,
    )

    app.include_router(sessions.router)
    app.include_router(workflows.router)
    app.include_router(notifications.router)
    app.include_router(github_webhook.router)

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

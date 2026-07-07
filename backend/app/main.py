"""FastAPI application factory for kestrel."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    # Surface the egress allowlist so an operator can confirm the proxy ACL
    # matches what kestrel actually reaches. Informational: kestrel does not
    # enforce egress itself (the network/proxy does) — see docs/security.md.
    from app.services.egress import derive_egress_allowlist

    _logger.info(
        "egress allowlist (hosts kestrel needs): %s%s",
        ", ".join(sorted(derive_egress_allowlist(settings))),
        f" | proxy: {settings.egress_proxy_url}"
        if settings.egress_proxy_url
        else " | no egress proxy configured (KESTREL_EGRESS_PROXY_URL)",
    )

    await get_workflow_service().recover()
    yield


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

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        """Readiness probe used by the container/compose healthcheck.

        Reports the running image version and verifies the database is
        reachable (a cheap ``SELECT 1``). Returns HTTP 503 if the DB is
        unreachable so an unready container is flagged rather than served.
        """
        from sqlalchemy import text

        from app.persistence.db import get_engine

        version = get_settings().version
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:  # pragma: no cover - defensive: DB down at runtime
            _logger.exception("healthz: database check failed")
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "version": version},
            )
        return JSONResponse(content={"status": "ok", "version": version})

    from fastapi import Depends

    from app.deps.auth import require_token
    from app.routers import notifications, sessions, workflows

    # Gate every /api route behind the shared-secret bearer token. A no-op
    # when KESTREL_API_TOKEN is unset (open dev mode); the server refuses a
    # non-loopback bind in that case (see app.__main__) so an open API is
    # never reachable off-host.
    api_auth = [Depends(require_token)]
    app.include_router(sessions.router, dependencies=api_auth)
    app.include_router(workflows.router, dependencies=api_auth)
    app.include_router(notifications.router, dependencies=api_auth)

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

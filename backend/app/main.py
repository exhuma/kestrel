"""FastAPI application factory for kestrel."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.services.exceptions import (
    InvalidWorkflowStateError,
    SessionNotFoundError,
    SessionStartError,
    WorkflowNotFoundError,
)


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(title="kestrel")

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

    @app.get("/")
    async def root() -> dict[str, str]:
        """Report basic service liveness."""
        return {"status": "ok"}

    from app.routers import sessions, workflows

    app.include_router(sessions.router)
    app.include_router(workflows.router)
    return app


app = create_app()

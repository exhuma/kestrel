"""FastAPI application factory for the agent dispatcher."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(title="agent-dispatcher")

    # Personal single-user dev tool: allow the SPA from any local
    # port (Vite may pick 5173, 5174, ... depending on what is free).
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://localhost:\d+",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root() -> dict[str, str]:
        """Report basic service liveness."""
        return {"status": "ok"}

    from app.routers import sessions

    app.include_router(sessions.router)
    return app


app = create_app()

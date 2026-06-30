"""FastAPI application factory for the agent dispatcher."""
from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(title="agent-dispatcher")

    @app.get("/")
    async def root() -> dict[str, str]:
        """Report basic service liveness."""
        return {"status": "ok"}

    return app


app = create_app()

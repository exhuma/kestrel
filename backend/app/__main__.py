"""Run the kestrel backend with unified logging.

This is the canonical entrypoint (``python -m app``): it hands a single
logging config to uvicorn so uvicorn's own logs and the application's logs
share one stdout stream and one format. Set ``KESTREL_RELOAD=1`` for the
auto-reloading dev server.
"""
from __future__ import annotations

import os

import uvicorn

from app.config import get_settings
from app.logging_config import build_log_config


def main() -> None:
    """Start uvicorn for ``app.main:app`` with the configured logging."""
    settings = get_settings()
    log_config = build_log_config(settings.log_level, settings.log_format)
    reload = os.environ.get("KESTREL_RELOAD", "").lower() in {
        "1",
        "true",
        "yes",
    }
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("KESTREL_HOST", "0.0.0.0"),
        port=int(os.environ.get("KESTREL_PORT", "8000")),
        log_config=log_config,
        reload=reload,
    )


if __name__ == "__main__":
    main()

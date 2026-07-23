"""Run the kestrel backend with unified logging.

This is the canonical entrypoint (``python -m app``): it hands a single
logging config to uvicorn so uvicorn's own logs and the application's logs
share one stdout stream and one format. Host, port and the dev auto-reload
toggle come from ``Settings`` (``KESTREL_HOST`` / ``KESTREL_PORT`` /
``KESTREL_RELOAD``), so a ``backend/.env`` value is honoured.
"""
from __future__ import annotations

import uvicorn

from app.config import get_settings
from app.logging_config import build_log_config


def main() -> None:
    """Start uvicorn for ``app.main:app`` with the configured logging."""
    settings = get_settings()
    log_config = build_log_config(settings.log_level, settings.log_format)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_config=log_config,
        reload=settings.reload,
    )


if __name__ == "__main__":
    main()

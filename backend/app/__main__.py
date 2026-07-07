"""Run the kestrel backend with unified logging.

This is the canonical entrypoint (``python -m app``): it hands a single
logging config to uvicorn so uvicorn's own logs and the application's logs
share one stdout stream and one format. Set ``KESTREL_RELOAD=1`` for the
auto-reloading dev server.
"""
from __future__ import annotations

import logging
import os

import uvicorn

from app.config import get_settings
from app.logging_config import build_log_config

_logger = logging.getLogger(__name__)

# Hosts that keep the API reachable only from the local machine. Binding
# anywhere else with no API token would expose an unauthenticated remote
# trigger for the agent, so that combination is refused below.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def main() -> None:
    """Start uvicorn for ``app.main:app`` with the configured logging."""
    settings = get_settings()
    log_config = build_log_config(settings.log_level, settings.log_format)
    reload = os.environ.get("KESTREL_RELOAD", "").lower() in {"1", "true", "yes"}
    host = os.environ.get("KESTREL_HOST", "127.0.0.1")

    # Fail closed: an open API (no KESTREL_API_TOKEN) must never listen on a
    # non-loopback interface, where it would be an unauthenticated remote
    # trigger for the shell-executing agent. A container legitimately binds
    # 0.0.0.0 *inside* its network namespace while the host publishes only to
    # loopback (see docker-compose.yml); such deployments set
    # KESTREL_ALLOW_INSECURE_BIND=1 to assert that isolation.
    allow_insecure = os.environ.get(
        "KESTREL_ALLOW_INSECURE_BIND", ""
    ).lower() in {"1", "true", "yes"}
    if not settings.api_token and host not in _LOOPBACK_HOSTS:
        if not allow_insecure:
            raise SystemExit(
                f"refusing to bind {host!r} without KESTREL_API_TOKEN: an "
                "open API may only listen on loopback. Set KESTREL_API_TOKEN, "
                "bind 127.0.0.1, or set KESTREL_ALLOW_INSECURE_BIND=1 if the "
                "host publishes this port to loopback only."
            )
        _logger.warning(
            "binding %r without KESTREL_API_TOKEN "
            "(KESTREL_ALLOW_INSECURE_BIND set): the /api surface is "
            "UNAUTHENTICATED — ensure the host publishes this port to "
            "loopback only.",
            host,
        )
    if not settings.api_token:
        _logger.warning(
            "KESTREL_API_TOKEN is not set: the /api surface is UNAUTHENTICATED "
            "(bound to loopback only)."
        )

    uvicorn.run(
        "app.main:app",
        host=host,
        port=int(os.environ.get("KESTREL_PORT", "8000")),
        log_config=log_config,
        reload=reload,
    )


if __name__ == "__main__":
    main()

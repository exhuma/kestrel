"""Cross-cutting HTTP middleware for kestrel.

Implements the ``module-http-middleware-hardening`` (v2) contract: one
structured log line per request, three security headers, and a version header.
Cross-request correlation is **not** a custom header — it rides W3C trace
context (``traceparent``) propagated by OpenTelemetry (see :mod:`app.telemetry`
and ``module-opentelemetry``); this middleware neither generates, reads, nor
echoes a correlation header. Log lines link to traces via the ``trace_id`` /
``span_id`` fields owned by :mod:`app.logging_config`.

These are written as **pure ASGI middleware** rather than Starlette's
``BaseHTTPMiddleware``. kestrel streams Server-Sent Events from long-lived
generators (see ``app.sse`` and the ``/events`` routes); ``BaseHTTPMiddleware``
buffers responses through a memory stream and can stall or break those
streams. Pure ASGI middleware only inspects/mutates the ``http.response.start``
message, so the response body streams through untouched.

Registered inside the application factory (see ``app.main.create_app``).
"""
from __future__ import annotations

import logging
import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    """Emit one structured log line per request.

    Logs method, path, client, status, and duration on success, and logs the
    same request context before re-raising on an unhandled exception. Trace
    correlation is automatic via ``trace_id`` / ``span_id`` — this middleware
    adds no correlation header.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client = scope["client"][0] if scope.get("client") else "unknown"
        method: str = scope["method"]
        path: str = scope["path"]
        start = time.monotonic()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            elapsed = (time.monotonic() - start) * 1000
            _logger.exception(
                "%s %s from %s failed after %.1f ms",
                method,
                path,
                client,
                elapsed,
            )
            raise
        elapsed = (time.monotonic() - start) * 1000
        _logger.info(
            "%s %s from %s -> %d (%.1f ms)",
            method,
            path,
            client,
            status,
            elapsed,
        )


class SecurityHeadersMiddleware:
    """Set the three required security headers on every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            await send(message)

        await self.app(scope, receive, send_wrapper)


class VersionHeaderMiddleware:
    """Stamp the running application version on every response.

    The version is injected at construction time; the middleware never reads
    settings or global state.
    """

    def __init__(self, app: ASGIApp, version: str) -> None:
        self.app = app
        self._version = version

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Kestrel-Version"] = (
                    self._version
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)

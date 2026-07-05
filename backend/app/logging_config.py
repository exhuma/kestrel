"""Unified logging for the kestrel backend.

One stdout stream carries both uvicorn's logs and the application's own
``logging`` records, in a single format. ``KESTREL_LOG_FORMAT`` selects
human-readable text (default) or one JSON document per line for a log
pipeline (OTEL, Logstash, …).

The container launches via ``python -m app`` (see ``app.__main__``), which
hands the config below to uvicorn so uvicorn's loggers propagate to the same
root handler — closing the gap between uvicorn output and app output.
"""
from __future__ import annotations

import contextvars
import datetime as _dt
import json
import logging
from typing import Any

#: Per-request correlation ID, shared by every log record emitted while a
#: request is in flight (see ``app.middleware.RequestLoggingMiddleware`` and
#: the ``module-http-middleware-hardening`` kit). ``"-"`` renders for records
#: emitted outside any request (startup, shutdown, background tasks).
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "kestrel_correlation_id", default=None
)


def set_correlation_id(cid: str) -> None:
    """Bind ``cid`` as the correlation ID for the current context."""
    _correlation_id.set(cid)


def clear_correlation_id() -> None:
    """Drop the correlation ID so it never leaks into the next request."""
    _correlation_id.set(None)


def get_correlation_id() -> str | None:
    """Return the correlation ID bound to the current context, if any."""
    return _correlation_id.get()


class CorrelationIDFilter(logging.Filter):
    """Stamp the current correlation ID onto every record it sees.

    Attached to the stream handler so both formatters can rely on the
    ``correlation_id`` attribute always being present.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Render a log record as a single-line JSON document."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _dt.datetime.fromtimestamp(
                record.created, tz=_dt.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        cid = getattr(record, "correlation_id", None)
        if cid and cid != "-":
            payload["correlation_id"] = cid
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str)


def build_log_config(level: str, fmt: str) -> dict[str, Any]:
    """Build a ``logging.config.dictConfig`` mapping.

    :param level: Root/uvicorn log level (e.g. ``"info"``).
    :param fmt: ``"text"`` or ``"json"``.
    :returns: A dictConfig ready for uvicorn's ``log_config``.
    """
    level = level.upper()
    formatter = "json" if fmt == "json" else "text"
    return {
        "version": 1,
        # Keep loggers created at import time (app modules) working.
        "disable_existing_loggers": False,
        "filters": {
            "correlation_id": {"()": f"{__name__}.CorrelationIDFilter"},
        },
        "formatters": {
            "text": {
                "format": (
                    "%(asctime)s %(levelname)-8s [%(correlation_id)s] "
                    "%(name)s: %(message)s"
                ),
            },
            "json": {"()": f"{__name__}.JsonFormatter"},
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": formatter,
                # The filter stamps correlation_id onto every record, so the
                # text format above can reference it unconditionally.
                "filters": ["correlation_id"],
            },
        },
        # Root owns the only handler; uvicorn's loggers propagate to it so
        # every line shares one stream and one format.
        "root": {"level": level, "handlers": ["default"]},
        "loggers": {
            "uvicorn": {"level": level, "handlers": [], "propagate": True},
            "uvicorn.error": {
                "level": level,
                "handlers": [],
                "propagate": True,
            },
            "uvicorn.access": {
                "level": level,
                "handlers": [],
                "propagate": True,
            },
        },
    }


def configure_logging(level: str, fmt: str) -> None:
    """Apply :func:`build_log_config` to the process logging state."""
    import logging.config

    logging.config.dictConfig(build_log_config(level, fmt))

"""Unified logging for the kestrel backend.

One stdout stream carries both uvicorn's logs and the application's own
``logging`` records, in a single format. ``KESTREL_LOG_FORMAT`` selects
human-readable text (default) or one JSON document per line for a log
pipeline (OTEL, Logstash, …).

The container launches via ``python -m app`` (see ``app.__main__``), which
hands the config below to uvicorn so uvicorn's loggers propagate to the same
root handler — closing the gap between uvicorn output and app output.

Per the ``module-logging-structured`` (v2) and ``module-opentelemetry`` kits,
cross-request correlation rides **W3C trace context**, not a custom
correlation header: each record carries ``trace_id`` / ``span_id`` fields,
enriched from the active span by OpenTelemetry's logging instrumentation
(installed by :mod:`app.telemetry` when telemetry is enabled). ``"-"`` renders
when no span is active — startup, shutdown, background work, or telemetry off.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
from typing import Any

#: Record attributes injected by OpenTelemetry's ``LoggingInstrumentor`` when
#: a span is active. The filter below maps them onto the stable
#: ``trace_id`` / ``span_id`` names both formatters read.
_OTEL_TRACE_ATTR = "otelTraceID"
_OTEL_SPAN_ATTR = "otelSpanID"


class TraceContextFilter(logging.Filter):
    """Stamp ``trace_id`` and ``span_id`` onto every record it sees.

    Attached to the stream handler so both formatters can rely on the
    attributes always being present. Values come from the span context that
    OpenTelemetry's logging instrumentation enriches onto the record
    (``otelTraceID`` / ``otelSpanID``); ``"-"`` renders when no span is active
    or telemetry is disabled.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = getattr(record, _OTEL_TRACE_ATTR, None) or "-"
        record.span_id = getattr(record, _OTEL_SPAN_ATTR, None) or "-"
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
        trace_id = getattr(record, "trace_id", None)
        if trace_id and trace_id != "-":
            payload["trace_id"] = trace_id
            span_id = getattr(record, "span_id", None)
            if span_id and span_id != "-":
                payload["span_id"] = span_id
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
            "trace_context": {"()": f"{__name__}.TraceContextFilter"},
        },
        "formatters": {
            "text": {
                "format": (
                    "%(asctime)s %(levelname)-8s [%(trace_id)s] "
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
                # The filter stamps trace_id/span_id onto every record, so the
                # text format above can reference trace_id unconditionally.
                "filters": ["trace_context"],
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

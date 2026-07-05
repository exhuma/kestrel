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

import datetime as _dt
import json
import logging
from typing import Any


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
        "formatters": {
            "text": {
                "format": "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            },
            "json": {"()": f"{__name__}.JsonFormatter"},
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": formatter,
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

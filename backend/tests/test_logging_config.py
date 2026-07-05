"""Tests for unified logging configuration."""
from __future__ import annotations

import json
import logging

from app.logging_config import JsonFormatter, build_log_config, configure_logging


def _record(**kw: object) -> logging.LogRecord:
    defaults = dict(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    defaults.update(kw)
    return logging.LogRecord(**defaults)  # type: ignore[arg-type]


def test_json_formatter_emits_single_line_document() -> None:
    """Ensure a record renders as one JSON line with the core fields."""
    line = JsonFormatter().format(_record())
    assert "\n" not in line
    doc = json.loads(line)
    assert doc["level"] == "INFO"
    assert doc["logger"] == "app.test"
    assert doc["message"] == "hello world"
    assert "timestamp" in doc


def test_json_formatter_includes_exception() -> None:
    """Ensure exc_info is captured under an ``exception`` key."""
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = _record(exc_info=sys.exc_info())
    doc = json.loads(JsonFormatter().format(rec))
    assert "boom" in doc["exception"]


def test_build_log_config_unifies_uvicorn_with_root() -> None:
    """Ensure uvicorn loggers propagate to the single root handler."""
    cfg = build_log_config("info", "json")
    assert cfg["root"]["handlers"] == ["default"]
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert cfg["loggers"][name]["handlers"] == []
        assert cfg["loggers"][name]["propagate"] is True
    assert cfg["handlers"]["default"]["formatter"] == "json"
    assert cfg["root"]["level"] == "INFO"


def test_build_log_config_text_is_default_format() -> None:
    """Ensure the text format selects the human-readable formatter."""
    cfg = build_log_config("debug", "text")
    assert cfg["handlers"]["default"]["formatter"] == "text"
    assert cfg["root"]["level"] == "DEBUG"


def test_configure_logging_installs_root_handler(capsys) -> None:
    """Ensure configure_logging routes a plain app logger to stdout.

    This is the fix for `uvicorn app.main:app` showing no app logs: the
    lifespan calls configure_logging so the root logger gains a handler at
    the requested level and app records surface.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        configure_logging("debug", "text")
        assert root.level == logging.DEBUG
        assert root.handlers  # a handler now exists on the root logger
        logging.getLogger("app.some.module").debug("hello-from-app")
        assert "hello-from-app" in capsys.readouterr().out
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)

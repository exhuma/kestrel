"""Tests for backend error diagnostics."""
from __future__ import annotations

import pytest

from app.backends.opencode import OpenCodeBackend
from app.config import BackendConfig, Settings
from app.storage.registry import SessionRegistry


def test_empty_opencode_error_gets_a_diagnostic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure a blank backend exception never produces a blank RESULT error."""
    registry = SessionRegistry()
    backend = OpenCodeBackend(
        Settings(_env_file=None), registry, BackendConfig(id="oc")
    )
    registry.create("oc-1", "/tmp/s")

    backend._record_turn_error("oc-1", "/tmp/s", RuntimeError())

    assert registry.get("oc-1").events[-1].text == (
        "opencode turn ended without an error message"
    )
    assert "failed without a diagnostic" in caplog.text

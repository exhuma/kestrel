"""Tests for application settings."""
from __future__ import annotations

import pytest

from app.config import Settings


def test_settings_read_kestrel_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure settings read the KESTREL_ environment prefix."""
    monkeypatch.setenv("KESTREL_CLAUDE_BIN", "/opt/claude")
    assert Settings().claude_bin == "/opt/claude"


def test_workspace_default_is_kestrel_branded() -> None:
    """Ensure the default workspace root is kestrel-branded."""
    assert Settings().workspace_root == "./.kestrel-workspaces"

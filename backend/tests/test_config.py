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


def test_github_settings_have_defaults() -> None:
    """Ensure GitHub settings default to the public API and github.com."""
    s = Settings(github_token="")
    assert s.github_api_base == "https://api.github.com"
    assert s.git_base == "https://github.com"


def test_github_settings_read_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure the KESTREL_ env prefix populates GitHub settings."""
    monkeypatch.setenv("KESTREL_GITHUB_TOKEN", "tok-123")
    monkeypatch.setenv(
        "KESTREL_GITHUB_API_BASE", "https://ghe.example/api/v3"
    )
    s = Settings()
    assert s.github_token == "tok-123"
    assert s.github_api_base == "https://ghe.example/api/v3"

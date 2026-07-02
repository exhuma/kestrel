"""Tests for application settings."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


def test_settings_read_kestrel_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure settings read the KESTREL_ environment prefix."""
    monkeypatch.setenv("KESTREL_CLAUDE_BIN", "/opt/claude")
    assert Settings(_env_file=None).claude_bin == "/opt/claude"


def test_workspace_default_is_kestrel_branded() -> None:
    """Ensure the default workspace root is kestrel-branded."""
    s = Settings(_env_file=None)
    assert s.workspace_root == "./.kestrel-workspaces"


def test_unknown_env_file_keys_are_ignored(
    tmp_path: Path,
) -> None:
    """Ensure stale env-file keys do not crash settings loading.

    A leftover ``DISPATCHER_``-prefixed entry (or any unrelated
    key) in ``.env`` must be ignored, not rejected as an extra
    input.
    """
    env = tmp_path / ".env"
    env.write_text(
        "DISPATCHER_CLAUDE_BIN=old\nUNRELATED_KEY=1\n"
    )
    s = Settings(_env_file=env)
    assert s.claude_bin == "claude"


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

"""Tests for application settings."""
from __future__ import annotations

from app.config import Settings


def test_github_settings_have_defaults() -> None:
    """Ensure GitHub settings default to the public API and github.com."""
    s = Settings(github_token="")
    assert s.github_api_base == "https://api.github.com"
    assert s.git_base == "https://github.com"


def test_github_settings_read_env(monkeypatch) -> None:
    """Ensure the DISPATCHER_ env prefix populates GitHub settings."""
    monkeypatch.setenv("DISPATCHER_GITHUB_TOKEN", "tok-123")
    monkeypatch.setenv("DISPATCHER_GITHUB_API_BASE", "https://ghe.example/api/v3")
    s = Settings()
    assert s.github_token == "tok-123"
    assert s.github_api_base == "https://ghe.example/api/v3"

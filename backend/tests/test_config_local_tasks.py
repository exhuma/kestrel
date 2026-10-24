"""Tests for local task source and development runtime TOML configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


def test_config_file_overrides_local_runtime_settings(tmp_path: Path) -> None:
    """Ensure selected TOML values override the development runtime state."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        "port = 9000\n"
        'database_url = "sqlite:///./test.db"\n'
        'workspace_root = "./workspaces"\n'
        "\n"
        "[[task_sources]]\n"
        'type = "local"\n'
        'tasks_dir = "./tasks"\n'
        'code_host = "local"\n'
    )
    settings = Settings(_env_file=None, config_file=str(toml))
    assert (settings.port, settings.database_url) == (
        9000,
        "sqlite:///./test.db",
    )
    assert settings.workspace_root == "./workspaces"
    assert settings.local_sources()[0].tasks_dir == "./tasks"


def test_fixture_source_configuration_is_rejected() -> None:
    """Ensure the breaking rename accepts no fixture source configuration."""
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            task_sources=[
                {"type": "fixture", "fixtures_dir": "./fixtures"}
            ],
        )

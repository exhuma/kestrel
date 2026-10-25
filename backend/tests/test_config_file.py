"""Tests for reading Settings from the TOML config file (``config.toml``)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings

_FILE, _ENV, _OTHER = 3, 4, 5


def _write(tmp_path: Path, text: str) -> str:
    """Write ``text`` as ``config.toml`` and return its path."""
    path = tmp_path / "config.toml"
    path.write_text(text)
    return str(path)


def test_any_setting_can_come_from_the_file(tmp_path: Path) -> None:
    """Ensure a field never on an allow-list is still read from the file."""
    path = _write(
        tmp_path,
        f"board_refinement_round_cap = {_FILE}\n"
        f"board_prd_redraft_cap = {_ENV}\n"
        'claude_bin = "/opt/claude"\n'
        'log_format = "json"\n',
    )
    s = Settings(_env_file=None, config_file=path)
    assert s.board_refinement_round_cap == _FILE
    assert s.board_prd_redraft_cap == _ENV
    assert s.claude_bin == "/opt/claude"
    assert s.log_format == "json"


def test_file_values_are_validated(tmp_path: Path) -> None:
    """Ensure a file value is checked like any other source's value."""
    path = _write(tmp_path, "board_refinement_round_cap = 0\n")
    with pytest.raises(ValueError, match="board_refinement_round_cap"):
        Settings(_env_file=None, config_file=path)


def test_file_wins_over_environment_over_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure precedence is file, then environment, then the default."""
    monkeypatch.setenv("KESTREL_BOARD_PRD_REDRAFT_CAP", str(_ENV))
    monkeypatch.setenv("KESTREL_BOARD_REFINEMENT_ROUND_CAP", str(_OTHER))
    path = _write(tmp_path, f"board_prd_redraft_cap = {_FILE}\n")
    s = Settings(_env_file=None, config_file=path)
    assert s.board_prd_redraft_cap == _FILE  # file beats the environment
    assert s.board_refinement_round_cap == _OTHER  # environment beats default
    assert s.board_unreadable_retry_cap == 1  # default


def test_config_file_path_comes_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure ``KESTREL_CONFIG_FILE`` alone selects the file."""
    path = _write(tmp_path, f"board_prd_redraft_cap = {_OTHER}\n")
    monkeypatch.setenv("KESTREL_CONFIG_FILE", path)
    assert Settings(_env_file=None).board_prd_redraft_cap == _OTHER


def test_unknown_top_level_key_fails_at_startup(tmp_path: Path) -> None:
    """Ensure a typo in a key is an error, not silently ignored."""
    path = _write(tmp_path, "board_prd_redraft_capp = 2\n")
    with pytest.raises(ValueError, match="board_prd_redraft_capp"):
        Settings(_env_file=None, config_file=path)


def test_missing_file_fails_at_startup(tmp_path: Path) -> None:
    """Ensure a configured but absent file is an error."""
    with pytest.raises(ValueError, match="config_file not found"):
        Settings(_env_file=None, config_file=str(tmp_path / "nope.toml"))


def test_malformed_file_fails_at_startup(tmp_path: Path) -> None:
    """Ensure invalid TOML is an error naming the file."""
    path = _write(tmp_path, "this is = = not valid toml")
    with pytest.raises(ValueError, match="invalid TOML"):
        Settings(_env_file=None, config_file=path)


def test_no_file_uses_defaults_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure an unset config_file falls back to defaults visibly."""
    with caplog.at_level("INFO"):
        s = Settings(_env_file=None)
    assert s.board_prd_redraft_cap == 1
    assert "no config file configured" in caplog.text

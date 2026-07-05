"""Tests for application settings."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import BackendConfig, Settings


def test_backend_secret_prefers_inline_then_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure secret() reads an inline value, else the named env var."""
    assert BackendConfig(id="x", password="pw").secret() == "pw"
    assert BackendConfig(id="x", api_key="key").secret() == "key"
    assert BackendConfig(id="x").secret() is None
    monkeypatch.setenv("MY_SECRET", "from-env")
    assert BackendConfig(id="x", api_key_env="MY_SECRET").secret() == "from-env"
    # An inline value wins over the env var.
    assert (
        BackendConfig(id="x", password="pw", api_key_env="MY_SECRET").secret()
        == "pw"
    )


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


def test_backends_file_supplies_backend_config(tmp_path: Path) -> None:
    """Ensure a TOML backends_file populates the backend settings."""
    toml = tmp_path / "backends.toml"
    toml.write_text(
        'default_session_backend = "oc"\n'
        "\n"
        "[step_backends]\n"
        'implement = "claude"\n'
        "\n"
        "[[backends]]\n"
        'id = "claude"\n'
        'type = "claude_cli"\n'
        "\n"
        "[[backends]]\n"
        'id = "oc"\n'
        'type = "opencode"\n'
        'base_url = "http://localhost:4096"\n'
        'model = "opencode/deepseek-v4-flash-free"\n'
    )
    s = Settings(_env_file=None, backends_file=str(toml))
    assert s.default_session_backend == "oc"
    assert s.step_backends == {"implement": "claude"}
    assert [(b.id, b.type) for b in s.backends] == [
        ("claude", "claude_cli"), ("oc", "opencode")
    ]
    assert s.backends[1].base_url == "http://localhost:4096"


def test_backend_env_vars_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure backends are file-only: the env vars have no effect.

    ``KESTREL_BACKENDS`` / ``KESTREL_STEP_BACKENDS`` /
    ``KESTREL_DEFAULT_SESSION_BACKEND`` were dropped in favour of
    ``KESTREL_BACKENDS_FILE``; setting them must not change config.
    """
    monkeypatch.setenv(
        "KESTREL_BACKENDS",
        '[{"id": "ghost", "type": "claude_cli"}]',
    )
    monkeypatch.setenv("KESTREL_DEFAULT_SESSION_BACKEND", "ghost")
    monkeypatch.setenv("KESTREL_STEP_BACKENDS", '{"plan": "ghost"}')
    s = Settings(_env_file=None)
    assert [b.id for b in s.backends] == ["claude"]
    assert s.default_session_backend == "claude"
    assert s.step_backends == {}


def test_backends_file_missing_fails_fast(tmp_path: Path) -> None:
    """Ensure a bad backends_file path raises at settings load."""
    with pytest.raises(Exception) as exc:
        Settings(_env_file=None, backends_file=str(tmp_path / "nope.toml"))
    assert "backends_file not found" in str(exc.value)


def test_backends_file_invalid_toml_fails_fast(tmp_path: Path) -> None:
    """Ensure malformed TOML in backends_file raises a clear error."""
    toml = tmp_path / "bad.toml"
    toml.write_text("this is = = not valid toml")
    with pytest.raises(Exception) as exc:
        Settings(_env_file=None, backends_file=str(toml))
    assert "invalid TOML" in str(exc.value)

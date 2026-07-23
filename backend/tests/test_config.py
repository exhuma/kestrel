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


def test_ingestion_settings_have_defaults() -> None:
    """Ensure the feature-002 ingestion settings default sensibly."""
    s = Settings(_env_file=None)
    assert s.webhook_secret == ""
    assert s.watched_repos == []
    assert s.trigger_label == "kestrel"
    assert s.reconcile_interval_seconds == 300
    assert s.public_base_url == ""


def test_watched_repos_parses_comma_separated() -> None:
    """Ensure watched_repos accepts a comma-separated string."""
    s = Settings(_env_file=None, watched_repos="a/b, c/d ,e/f")
    assert s.watched_repos == ["a/b", "c/d", "e/f"]


def test_watched_repos_parses_json_list() -> None:
    """Ensure watched_repos accepts a JSON array string."""
    s = Settings(_env_file=None, watched_repos='["a/b", "c/d"]')
    assert s.watched_repos == ["a/b", "c/d"]


def test_watched_repos_reads_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure KESTREL_WATCHED_REPOS parses a comma-separated env value."""
    monkeypatch.setenv("KESTREL_WATCHED_REPOS", "o/one,o/two")
    assert Settings().watched_repos == ["o/one", "o/two"]


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


def test_jira_settings_have_defaults() -> None:
    """Ensure the feature-003 Jira settings default sensibly."""
    s = Settings(_env_file=None)
    assert s.jira_base_url == ""
    assert s.jira_auth == "basic"
    assert s.jira_email == ""
    assert s.jira_api_token == ""
    assert s.jira_project == ""
    assert s.jira_jql_filter == ""
    assert s.jira_repo_field == ""
    assert s.jira_poll_interval_seconds == 300


def test_code_host_and_verify_defaults() -> None:
    """Ensure code-host and verify settings default sensibly."""
    s = Settings(_env_file=None)
    assert s.code_host == "github"
    assert s.code_host_base_url == ""
    assert s.code_host_token == ""
    assert s.verify_checks == []
    assert s.max_verify_iterations == 3


def test_jira_auth_and_code_host_accept_literals() -> None:
    """Ensure the literal-typed settings accept their allowed values."""
    assert Settings(_env_file=None, jira_auth="bearer").jira_auth == "bearer"
    assert Settings(_env_file=None, code_host="gitlab").code_host == "gitlab"
    assert Settings(_env_file=None, code_host="gitea").code_host == "gitea"
    with pytest.raises(Exception):
        Settings(_env_file=None, jira_auth="oauth")
    with pytest.raises(Exception):
        Settings(_env_file=None, code_host="bitbucket")


def test_verify_checks_parses_json_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure KESTREL_VERIFY_CHECKS parses a JSON array from the env."""
    monkeypatch.setenv(
        "KESTREL_VERIFY_CHECKS", '["uv run pytest -q", "npm test"]'
    )
    assert Settings().verify_checks == ["uv run pytest -q", "npm test"]


def test_jira_partial_config_warns_without_leaking_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A half-configured Jira setup warns, and never logs the token."""
    with caplog.at_level("WARNING"):
        Settings(
            _env_file=None,
            jira_base_url="https://jira.example",
            jira_api_token="super-secret-token",
        )
    text = caplog.text
    assert "jira_project" in text
    assert "super-secret-token" not in text


def test_code_host_partial_config_warns_without_leaking_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A self-hosted code host with no URL/token warns, without the token."""
    with caplog.at_level("WARNING"):
        Settings(
            _env_file=None,
            code_host="gitlab",
            code_host_token="ch-secret-token",
        )
    text = caplog.text
    assert "code_host_base_url" in text
    assert "ch-secret-token" not in text


def test_full_jira_and_code_host_config_does_not_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A complete config emits no ingestion/code-host warning."""
    with caplog.at_level("WARNING"):
        Settings(
            _env_file=None,
            jira_base_url="https://jira.example",
            jira_project="RFC",
            jira_api_token="t",
            code_host="gitlab",
            code_host_base_url="https://gitlab.internal",
            code_host_token="t",
        )
    assert "jira_project" not in caplog.text
    assert "code_host_base_url is" not in caplog.text


def test_backends_file_missing_fails_fast(tmp_path: Path) -> None:
    """Ensure a bad config-file path raises at settings load."""
    with pytest.raises(Exception) as exc:
        Settings(_env_file=None, backends_file=str(tmp_path / "nope.toml"))
    assert "config_file not found" in str(exc.value)


def test_backends_file_invalid_toml_fails_fast(tmp_path: Path) -> None:
    """Ensure malformed TOML in the config file raises a clear error."""
    toml = tmp_path / "bad.toml"
    toml.write_text("this is = = not valid toml")
    with pytest.raises(Exception) as exc:
        Settings(_env_file=None, backends_file=str(toml))
    assert "invalid TOML" in str(exc.value)


def test_config_file_supplies_backend_config(tmp_path: Path) -> None:
    """Ensure the new config_file populates the backend settings."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        'default_session_backend = "oc"\n'
        "\n"
        "[step_backends]\n"
        'implement = "claude"\n'
        "\n"
        "[[backends]]\n"
        'id = "oc"\n'
        'type = "opencode"\n'
    )
    s = Settings(_env_file=None, config_file=str(toml))
    assert s.default_session_backend == "oc"
    assert s.step_backends == {"implement": "claude"}
    assert [b.id for b in s.backends] == ["oc"]


def test_config_file_overlays_applicative_settings(tmp_path: Path) -> None:
    """Ensure applicative keys are read from the config file.

    ``watched_repos`` (native TOML array), plus the ingestion/reconcile
    knobs, come from the file rather than the environment.
    """
    toml = tmp_path / "config.toml"
    toml.write_text(
        'watched_repos = ["o/one", "o/two"]\n'
        'trigger_label = "ship-it"\n'
        "reconcile_interval_seconds = 60\n"
        'verify_checks = ["uv run pytest -q"]\n'
        "max_verify_iterations = 5\n"
    )
    s = Settings(_env_file=None, config_file=str(toml))
    assert s.watched_repos == ["o/one", "o/two"]
    assert s.trigger_label == "ship-it"
    assert s.reconcile_interval_seconds == 60
    assert s.verify_checks == ["uv run pytest -q"]
    assert s.max_verify_iterations == 5


def test_config_file_wins_over_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure the file overrides an env value for a key it sets."""
    monkeypatch.setenv("KESTREL_WATCHED_REPOS", "env/repo")
    monkeypatch.setenv("KESTREL_MAX_VERIFY_ITERATIONS", "9")
    toml = tmp_path / "config.toml"
    toml.write_text(
        'watched_repos = ["file/repo"]\nmax_verify_iterations = 2\n'
    )
    s = Settings(config_file=str(toml))
    assert s.watched_repos == ["file/repo"]
    assert s.max_verify_iterations == 2


def test_env_fallback_when_file_omits_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure env still applies for applicative keys the file omits."""
    monkeypatch.setenv("KESTREL_WATCHED_REPOS", "env/repo")
    toml = tmp_path / "config.toml"
    # File sets only trigger_label; watched_repos must fall back to env.
    toml.write_text('trigger_label = "ship-it"\n')
    s = Settings(config_file=str(toml))
    assert s.watched_repos == ["env/repo"]
    assert s.trigger_label == "ship-it"


def test_backends_file_is_deprecated_alias(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Ensure backends_file still works but warns as deprecated."""
    toml = tmp_path / "backends.toml"
    toml.write_text('default_session_backend = "oc"\n')
    with caplog.at_level("WARNING"):
        s = Settings(_env_file=None, backends_file=str(toml))
    assert s.default_session_backend == "oc"
    assert "KESTREL_BACKENDS_FILE is deprecated" in caplog.text


def test_config_file_takes_precedence_over_backends_file(
    tmp_path: Path,
) -> None:
    """Ensure config_file wins when both are set (no deprecation path)."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('default_session_backend = "cfg"\n')
    old = tmp_path / "backends.toml"
    old.write_text('default_session_backend = "old"\n')
    s = Settings(
        _env_file=None, config_file=str(cfg), backends_file=str(old)
    )
    assert s.default_session_backend == "cfg"

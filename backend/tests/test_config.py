"""Tests for application settings."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from app.config import Settings
from app.config_models import BackendConfig, TaskSourceConfig


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


def test_host_and_port_read_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure host/port load through Settings (so .env is honoured)."""
    monkeypatch.setenv("KESTREL_HOST", "127.0.0.1")
    monkeypatch.setenv("KESTREL_PORT", "9001")
    s = Settings(_env_file=None)
    assert (s.host, s.port) == ("127.0.0.1", 9001)


def test_host_and_port_defaults() -> None:
    """Ensure the server fields keep their documented defaults."""
    s = Settings(_env_file=None)
    assert (s.host, s.port) == ("0.0.0.0", 8000)


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
    """Ensure the feature-002/004 ingestion settings default sensibly."""
    s = Settings(_env_file=None)
    assert s.webhook_secret == ""
    assert s.task_sources == []
    assert s.poll_interval_seconds == 300
    assert s.public_base_url == ""


def test_github_source_for_matches_by_repo() -> None:
    """Ensure github_source_for returns the entry watching a repo, else None."""
    a = TaskSourceConfig(type="github", watched_repos=["o/a"])
    b = TaskSourceConfig(
        type="github", watched_repos=["o/b"], trigger_label="x"
    )
    s = Settings(_env_file=None, task_sources=[a, b])
    assert s.github_source_for("o/b").trigger_label == "x"
    assert s.github_source_for("o/none") is None
    assert [g.watched_repos for g in s.github_sources()] == [["o/a"], ["o/b"]]


def test_task_source_validation_rejects_incomplete_entries() -> None:
    """Ensure per-type required fields are enforced loudly."""
    with pytest.raises(Exception):
        TaskSourceConfig(type="github", watched_repos=[])
    with pytest.raises(Exception):
        TaskSourceConfig(type="jira", base_url="https://j", jql="", key="RFC")


def test_task_source_token_resolves_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure token() reads the named env var, defaulting per type."""
    monkeypatch.setenv("KESTREL_GITHUB_TOKEN", "gh-default")
    monkeypatch.setenv("CUSTOM_JIRA", "jira-custom")
    gh = TaskSourceConfig(type="github", watched_repos=["o/a"])
    jira = TaskSourceConfig(
        type="jira", base_url="https://j", jql="project = RFC", key="RFC",
        token_env="CUSTOM_JIRA",
    )
    assert gh.token() == "gh-default"
    assert jira.token() == "jira-custom"


def test_config_file_supplies_all_backend_fields(tmp_path: Path) -> None:
    """Ensure a TOML config file populates the backend settings."""
    toml = tmp_path / "backends.toml"
    toml.write_text(
        'default_session_backend = "oc"\n'
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
    s = Settings(_env_file=None, config_file=str(toml))
    assert s.default_session_backend == "oc"
    assert [(b.id, b.type) for b in s.backends] == [
        ("claude", "claude_cli"), ("oc", "opencode")
    ]
    assert s.backends[1].base_url == "http://localhost:4096"


def test_backend_env_vars_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure backends are file-only: the env vars have no effect.

    ``KESTREL_BACKENDS`` / ``KESTREL_DEFAULT_SESSION_BACKEND`` were dropped
    in favour of ``KESTREL_CONFIG_FILE``; setting them must not change
    config.
    """
    monkeypatch.setenv(
        "KESTREL_BACKENDS",
        '[{"id": "ghost", "type": "claude_cli"}]',
    )
    monkeypatch.setenv("KESTREL_DEFAULT_SESSION_BACKEND", "ghost")
    s = Settings(_env_file=None)
    assert [b.id for b in s.backends] == ["claude"]
    assert s.default_session_backend == "claude"


def test_jira_source_defaults_and_verify_defaults() -> None:
    """Ensure a Jira task source and max_verify_iterations default sensibly."""
    s = Settings(_env_file=None)
    assert s.max_verify_iterations == 3
    jira = TaskSourceConfig(
        type="jira", base_url="https://j", jql="project = RFC", key="RFC"
    )
    assert jira.auth == "basic"
    assert jira.repo_link_text == "Repository"
    assert jira.code_host == "github"
    assert jira.verify_ssl is True


def test_task_source_literals_accept_allowed_values() -> None:
    """Ensure the literal-typed source fields accept their allowed values."""
    def _jira(**kw):
        return TaskSourceConfig(
            type="jira", base_url="https://j", jql="q", key="RFC", **kw
        )

    assert _jira(auth="bearer").auth == "bearer"
    assert _jira(code_host="gitlab").code_host == "gitlab"
    assert _jira(code_host="gitea").code_host == "gitea"
    with pytest.raises(Exception):
        _jira(auth="oauth")
    with pytest.raises(Exception):
        _jira(code_host="bitbucket")


def test_jira_source_without_token_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A Jira source whose token env is unset warns at startup."""
    monkeypatch.delenv("KESTREL_JIRA_API_TOKEN", raising=False)
    with caplog.at_level("WARNING"):
        Settings(
            _env_file=None,
            task_sources=[
                TaskSourceConfig(
                    type="jira", base_url="https://jira.example",
                    jql="project = RFC", key="RFC",
                )
            ],
        )
    assert "no token" in caplog.text


def test_code_host_partial_config_warns_without_leaking_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A self-hosted code host with no URL/token warns, without the token."""
    monkeypatch.setenv("KESTREL_CODE_HOST_TOKEN", "ch-secret-token")
    with caplog.at_level("WARNING"):
        Settings(
            _env_file=None,
            task_sources=[
                TaskSourceConfig(
                    type="jira", base_url="https://jira.example",
                    jql="q", key="RFC", token_env="KESTREL_CODE_HOST_TOKEN",
                    code_host="gitlab",
                )
            ],
        )
    text = caplog.text
    assert "base URL or" in text
    assert "ch-secret-token" not in text


def test_full_jira_and_code_host_config_does_not_warn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A complete Jira source config emits no ingestion/code-host warning."""
    monkeypatch.setenv("KESTREL_JIRA_API_TOKEN", "t")
    monkeypatch.setenv("KESTREL_CODE_HOST_TOKEN", "t")
    with caplog.at_level("WARNING"):
        Settings(
            _env_file=None,
            task_sources=[
                TaskSourceConfig(
                    type="jira", base_url="https://jira.example",
                    jql="project = RFC", key="RFC",
                    code_host="gitlab",
                    code_host_base_url="https://gitlab.internal",
                )
            ],
        )
    assert "no token" not in caplog.text
    assert "base URL or" not in caplog.text


def test_config_file_missing_fails_fast(tmp_path: Path) -> None:
    """Ensure a bad config-file path raises at settings load."""
    with pytest.raises(Exception) as exc:
        Settings(_env_file=None, config_file=str(tmp_path / "nope.toml"))
    assert "config_file not found" in str(exc.value)


def test_config_file_invalid_toml_fails_fast(tmp_path: Path) -> None:
    """Ensure malformed TOML in the config file raises a clear error."""
    toml = tmp_path / "bad.toml"
    toml.write_text("this is = = not valid toml")
    with pytest.raises(Exception) as exc:
        Settings(_env_file=None, config_file=str(toml))
    assert "invalid TOML" in str(exc.value)


def test_config_file_supplies_backend_config(tmp_path: Path) -> None:
    """Ensure the new config_file populates the backend settings."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        'default_session_backend = "oc"\n'
        "\n"
        "[[backends]]\n"
        'id = "oc"\n'
        'type = "opencode"\n'
    )
    s = Settings(_env_file=None, config_file=str(toml))
    assert s.default_session_backend == "oc"
    assert [b.id for b in s.backends] == ["oc"]


def test_default_session_backend_after_backends_table_fails_loud(
    tmp_path: Path,
) -> None:
    """Ensure the TOML ordering trap fails at load time, not silently.

    A bare key after an array-of-tables header belongs to that table in
    TOML, not the top level — `default_session_backend` placed after
    `[[backends]]` here is swallowed into the backends entry, so it
    must be rejected loudly (BackendConfig's extra="forbid") rather
    than silently leaving default_session_backend at its "claude"
    default.
    """
    toml = tmp_path / "config.toml"
    toml.write_text(
        "[[backends]]\n"
        'id = "oc"\n'
        'type = "opencode"\n'
        "\n"
        'default_session_backend = "oc"\n'
    )
    with pytest.raises(ValueError, match="default_session_backend"):
        Settings(_env_file=None, config_file=str(toml))


def test_config_file_path_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Ensure the resolved path actually opened is visible in the logs —
    the main diagnostic for "my config edit had no effect"."""
    toml = tmp_path / "config.toml"
    toml.write_text('default_session_backend = "oc"\n')
    with caplog.at_level("INFO"):
        Settings(_env_file=None, config_file=str(toml))
    assert f"loading config file: {toml.resolve()}" in caplog.text


def test_missing_config_file_setting_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure an unset config_file is visible in the logs,
    not just a silent fall-through to the claude-only default."""
    with caplog.at_level("INFO"):
        Settings(_env_file=None)
    assert "no config file configured" in caplog.text


def test_config_file_supplies_task_sources(tmp_path: Path) -> None:
    """Ensure the file-only ``[[task_sources]]`` list parses two entries."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        "poll_interval_seconds = 60\n"
        "\n"
        "[[task_sources]]\n"
        'type = "github"\n'
        'watched_repos = ["o/one", "o/two"]\n'
        'trigger_label = "ship-it"\n'
        "\n"
        "[[task_sources]]\n"
        'type = "jira"\n'
        'base_url = "https://jira.example"\n'
        'jql = "project = RFC"\n'
        'key = "RFC"\n'
        "verify_ssl = false\n"
    )
    s = Settings(_env_file=None, config_file=str(toml))
    assert s.poll_interval_seconds == 60
    gh, jira = s.github_sources()[0], s.jira_sources()[0]
    assert gh.watched_repos == ["o/one", "o/two"]
    assert gh.trigger_label == "ship-it"
    assert jira.key == "RFC" and jira.jql == "project = RFC"
    assert jira.verify_ssl is False  # opt-out parsed from the file
    assert gh.verify_ssl is True  # default




def test_poll_interval_settable_via_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure poll_interval_seconds is applicative: the file wins over env."""
    monkeypatch.setenv("KESTREL_POLL_INTERVAL_SECONDS", "111")
    toml = tmp_path / "config.toml"
    toml.write_text("poll_interval_seconds = 222\n")
    assert Settings(config_file=str(toml)).poll_interval_seconds == 222


def test_env_fallback_when_file_omits_applicative_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure env still applies for applicative keys the file omits."""
    monkeypatch.setenv("KESTREL_POLL_INTERVAL_SECONDS", "150")
    toml = tmp_path / "config.toml"
    # File sets only max_verify_iterations; the interval falls back to env.
    toml.write_text("max_verify_iterations = 5\n")
    s = Settings(config_file=str(toml))
    assert s.poll_interval_seconds == 150
    assert s.max_verify_iterations == 5


def test_legacy_interval_env_key_is_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure a removed interval env key no longer affects the cadence."""
    monkeypatch.setenv("KESTREL_RECONCILE_INTERVAL_SECONDS", "99")
    monkeypatch.setenv("KESTREL_JIRA_POLL_INTERVAL_SECONDS", "77")
    # The old keys are gone (extra="ignore" makes them inert); the unified
    # default governs both loops.
    assert Settings(_env_file=None).poll_interval_seconds == 300


def test_cab1_interview_max_questions_defaults_to_three() -> None:
    """Ensure the CAB-1 strategic interview's question cap defaults low."""
    assert Settings(_env_file=None).board_cab1_interview_max_questions == 3


def test_cab1_interview_max_questions_rejects_non_positive() -> None:
    """Ensure a non-positive question cap fails validation loudly."""
    with pytest.raises(
        ValueError, match="board_cab1_interview_max_questions"
    ):
        Settings(_env_file=None, board_cab1_interview_max_questions=0)




def test_every_documented_top_level_key_is_read_from_the_file() -> None:
    """Ensure config.toml.example documents nothing the loader silently
    ignores (#70: CAB-1's switch and cap, and the health-check timings,
    were documented but never read)."""
    example = tomllib.loads(
        (Path(__file__).parents[2] / "config.toml.example").read_text()
    )
    scalars = {
        key for key, value in example.items()
        if not isinstance(value, (dict, list))
    }
    readable = set(Settings.model_fields)

    assert scalars - readable == set()

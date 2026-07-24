"""Tests for application settings."""
from __future__ import annotations

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


def test_host_port_reload_read_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure host/port/reload load through Settings (so .env is honoured)."""
    monkeypatch.setenv("KESTREL_HOST", "127.0.0.1")
    monkeypatch.setenv("KESTREL_PORT", "9001")
    monkeypatch.setenv("KESTREL_RELOAD", "true")
    s = Settings(_env_file=None)
    assert (s.host, s.port, s.reload) == ("127.0.0.1", 9001, True)


def test_host_port_reload_defaults() -> None:
    """Ensure the server fields keep their documented defaults."""
    s = Settings(_env_file=None)
    assert (s.host, s.port, s.reload) == ("0.0.0.0", 8000, False)


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


def test_backends_file_supplies_backend_config(tmp_path: Path) -> None:
    """Ensure a TOML backends_file populates the backend settings."""
    toml = tmp_path / "backends.toml"
    toml.write_text(
        'default_session_backend = "oc"\n'
        "\n"
        "[step_backends]\n"
        'code = "claude"\n'
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
    assert s.step_backends == {"code": "claude"}
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


def test_jira_source_defaults_and_verify_defaults() -> None:
    """Ensure a Jira task source and the verify settings default sensibly."""
    s = Settings(_env_file=None)
    assert s.jira_api_token == ""
    assert s.verify_checks == []
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


def test_verify_checks_parses_json_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure KESTREL_VERIFY_CHECKS parses a JSON array from the env."""
    monkeypatch.setenv(
        "KESTREL_VERIFY_CHECKS", '["uv run pytest -q", "npm test"]'
    )
    assert Settings().verify_checks == ["uv run pytest -q", "npm test"]


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
        'code = "claude"\n'
        "\n"
        "[[backends]]\n"
        'id = "oc"\n'
        'type = "opencode"\n'
    )
    s = Settings(_env_file=None, config_file=str(toml))
    assert s.default_session_backend == "oc"
    assert s.step_backends == {"code": "claude"}
    assert [b.id for b in s.backends] == ["oc"]


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


def test_step_backends_rejects_invalid_step_names(tmp_path: Path) -> None:
    """Ensure invalid step names in step_backends fail fast with clear error."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        "[step_backends]\n"
        'plan = "claude"\n'
        'implement = "claude"\n'
    )
    with pytest.raises(ValueError) as exc:
        Settings(_env_file=None, config_file=str(toml))
    msg = str(exc.value)
    assert "Invalid step names" in msg
    assert "plan" in msg
    assert "implement" in msg
    assert "design" in msg
    assert "code" in msg


def test_step_backends_accepts_valid_step_names(tmp_path: Path) -> None:
    """Ensure valid step names are accepted without error."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        "[step_backends]\n"
        'refine = "claude"\n'
        'design = "claude"\n'
        'code = "claude"\n'
        'verify = "claude"\n'
    )
    s = Settings(_env_file=None, config_file=str(toml))
    assert s.step_backends == {
        "refine": "claude",
        "design": "claude",
        "code": "claude",
        "verify": "claude",
    }


def test_step_backends_accepts_partial_valid_steps(tmp_path: Path) -> None:
    """Ensure omitting some steps is allowed (they use defaults)."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        "[step_backends]\n"
        'refine = "haiku"\n'
        'code = "sonnet"\n'
    )
    s = Settings(_env_file=None, config_file=str(toml))
    assert s.step_backends == {"refine": "haiku", "code": "sonnet"}


def test_step_backends_empty_is_valid(tmp_path: Path) -> None:
    """Ensure an empty step_backends section is valid."""
    toml = tmp_path / "config.toml"
    toml.write_text("[step_backends]\n")
    s = Settings(_env_file=None, config_file=str(toml))
    assert s.step_backends == {}


def test_step_backends_allows_sub_step_names(tmp_path: Path) -> None:
    """Ensure dotted sub-step names like 'refine.reconcile' are allowed."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        "[step_backends]\n"
        'refine = "claude"\n'
        'refine.reconcile = "haiku"\n'
        'code = "sonnet"\n'
    )
    s = Settings(_env_file=None, config_file=str(toml))
    assert s.step_backends == {
        "refine": "claude",
        "refine.reconcile": "haiku",
        "code": "sonnet",
    }


def test_step_backends_rejects_invalid_sub_step_names(tmp_path: Path) -> None:
    """Ensure invalid sub-steps (e.g. 'plan.xyz') are rejected."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        "[step_backends]\n"
        'plan.xyz = "claude"\n'
    )
    with pytest.raises(ValueError) as exc:
        Settings(_env_file=None, config_file=str(toml))
    msg = str(exc.value)
    assert "Invalid step names" in msg
    assert "plan" in msg

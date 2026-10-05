"""Settings for the ticket channel (feature 046)."""
from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.config_models import TaskSourceConfig

CUSTOM_POLL_SECONDS = 30.0
CUSTOM_RETRY_SECONDS = 90.0
DEFAULT_POLL_SECONDS = 60.0
DEFAULT_RETRY_SECONDS = 120.0


def test_jira_channel_settings_read_from_the_config_file(
    tmp_path: Path,
) -> None:
    """Ensure feature 046's settings can be set in config.toml."""
    toml = tmp_path / "config.toml"
    toml.write_text(
        'feedback_marker = "@bot"\n'
        f"board_comment_poll_interval_seconds = {CUSTOM_POLL_SECONDS}\n"
        f"board_projection_retry_interval_seconds = {CUSTOM_RETRY_SECONDS}\n"
        "\n"
        "[[task_sources]]\n"
        'type = "jira"\n'
        'base_url = "https://jira.example"\n'
        'jql = "project = RFC"\n'
        'key = "RFC"\n'
        'change_owner_field = "customfield_10051"\n'
    )
    s = Settings(_env_file=None, config_file=str(toml))
    assert s.feedback_marker == "@bot"
    assert s.board_comment_poll_interval_seconds == CUSTOM_POLL_SECONDS
    assert s.board_projection_retry_interval_seconds == CUSTOM_RETRY_SECONDS
    assert s.task_sources[0].change_owner_field == "customfield_10051"


def test_jira_channel_settings_defaults() -> None:
    """Ensure the reply marker and the two new intervals have defaults."""
    s = Settings(_env_file=None)
    assert s.feedback_marker == "@kestrel"
    assert s.board_comment_poll_interval_seconds == DEFAULT_POLL_SECONDS
    assert s.board_projection_retry_interval_seconds == DEFAULT_RETRY_SECONDS
    github = TaskSourceConfig(type="github", watched_repos=["o/a"])
    assert github.change_owner_field == ""

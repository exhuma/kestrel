"""Application configuration via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the dispatcher backend."""

    model_config = SettingsConfigDict(
        env_prefix="DISPATCHER_", env_file=".env"
    )

    claude_bin: str = "claude"
    workspace_root: str = "./.dispatcher-workspaces"
    permission_mode: str = "acceptEdits"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()

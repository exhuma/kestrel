"""Application configuration via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the kestrel backend."""

    model_config = SettingsConfigDict(
        env_prefix="KESTREL_",
        env_file=".env",
        # Stale or unrelated keys in .env (e.g. from before a
        # rename) must never crash startup.
        extra="ignore",
    )

    claude_bin: str = "claude"
    workspace_root: str = "./.kestrel-workspaces"
    permission_mode: str = "acceptEdits"
    # Directory of the built SPA to serve. Empty (dev default) means the
    # backend is API-only and the SPA is served by the Vite dev server; the
    # container image sets this to the baked-in static bundle.
    static_dir: str = ""
    github_token: str = ""
    github_api_base: str = "https://api.github.com"
    git_base: str = "https://github.com"
    database_url: str = "sqlite:///./kestrel.db"
    model_overrides: dict[str, str] = {}


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()

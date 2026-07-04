"""Application configuration via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendConfig(BaseModel):
    """One dispatchable agent backend.

    ``type`` selects the adapter; the remaining fields configure it
    (``base_url``/``model``/``api_key_env`` are used by the HTTP-based
    backends added in later phases). ``caps`` overrides the adapter's
    default capabilities when set.
    """

    id: str
    type: Literal["claude_cli", "opencode", "openai_compat"] = "claude_cli"
    base_url: str | None = None
    model: str | None = None
    #: Name of the env var holding this backend's secret — a bearer API
    #: key (``openai_compat``) or the HTTP Basic password (``opencode``).
    api_key_env: str | None = None
    #: HTTP Basic username for a secured ``opencode`` server. Defaults to
    #: opencode's own default ("opencode") when a password is configured.
    username: str | None = None
    caps: list[str] | None = None


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
    #: Dispatchable agent backends. Defaults to claude-only, preserving
    #: today's behavior. Supply as JSON via ``KESTREL_BACKENDS``.
    backends: list[BackendConfig] = Field(
        default_factory=lambda: [BackendConfig(id="claude", type="claude_cli")]
    )
    #: Per-workflow-step backend assignment (step name -> backend id).
    #: Steps not listed use the step's default backend.
    step_backends: dict[str, str] = {}
    #: Backend used for ad-hoc ``/api/sessions`` dispatch.
    default_session_backend: str = "claude"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()

"""Application configuration via pydantic-settings."""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# Backend config is file-only: these keys are resolved from the TOML file
# named by ``KESTREL_BACKENDS_FILE`` (or left at their claude-only defaults),
# never from the environment. Filtered out of the env/dotenv sources below.
_FILE_ONLY_FIELDS = frozenset(
    {"backends", "step_backends", "default_session_backend"}
)


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
    #: This backend's secret, given directly (fine in a gitignored config
    #: file): a bearer API key (``openai_compat``) or the HTTP Basic
    #: password (``opencode``). Prefer ``api_key`` / ``password``; these
    #: aliases are equivalent.
    api_key: str | None = None
    password: str | None = None
    #: Name of an env var holding the secret instead of giving it inline
    #: (used when the value is provided by the environment). Takes effect
    #: only when the direct secret above is unset.
    api_key_env: str | None = None
    #: HTTP Basic username for a secured ``opencode`` server. Defaults to
    #: opencode's own default ("opencode") when a password is configured.
    username: str | None = None
    #: Per-request timeout in seconds for HTTP backends (openai/opencode).
    timeout: float | None = None
    caps: list[str] | None = None

    def secret(self) -> str | None:
        """The resolved secret: an inline value, else the named env var."""
        import os

        direct = self.api_key or self.password
        if direct:
            return direct
        return os.environ.get(self.api_key_env) if self.api_key_env else None


class Settings(BaseSettings):
    """Runtime configuration for the kestrel backend."""

    model_config = SettingsConfigDict(
        env_prefix="KESTREL_",
        env_file=".env",
        # Stale or unrelated keys in .env (e.g. from before a
        # rename) must never crash startup.
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Drop the file-only backend keys from the environment sources.

        Backends are configured exclusively via ``KESTREL_BACKENDS_FILE``
        (or direct construction). Filtering these keys out of the env and
        dotenv sources makes any stray ``KESTREL_BACKENDS`` /
        ``KESTREL_STEP_BACKENDS`` / ``KESTREL_DEFAULT_SESSION_BACKEND``
        inert, while init kwargs and the file overlay still apply.
        """

        def _drop_file_only(
            source: PydanticBaseSettingsSource,
        ) -> PydanticBaseSettingsSource:
            def _call() -> dict[str, object]:
                return {
                    k: v
                    for k, v in source().items()
                    if k not in _FILE_ONLY_FIELDS
                }

            return _call  # type: ignore[return-value]

        return (
            init_settings,
            _drop_file_only(env_settings),
            _drop_file_only(dotenv_settings),
            file_secret_settings,
        )

    #: The running image's version, baked in at build time via
    #: ``KESTREL_VERSION`` (see the Dockerfile). The dev default makes a
    #: from-source run recognisable. Reported by ``GET /healthz``.
    version: str = "0.0.0-dev"
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
    #: Console log verbosity (``KESTREL_LOG_LEVEL``): debug/info/warning/…
    log_level: str = "info"
    #: Console log format (``KESTREL_LOG_FORMAT``): ``text`` for
    #: human-readable lines (default), ``json`` for one JSON document per
    #: line to feed a log pipeline (OTEL, Logstash, …).
    log_format: Literal["text", "json"] = "text"
    #: Path to a TOML file holding the backend config (``backends``,
    #: ``step_backends``, ``default_session_backend``). This file is the
    #: single way to configure backends — the recommended pattern is to
    #: mount it as a volume in Docker. Relative paths resolve against the
    #: working directory.
    backends_file: str = ""
    #: Dispatchable agent backends. File-only (see ``_FILE_ONLY_FIELDS``):
    #: resolved from ``backends_file`` or left at this claude-only default,
    #: never from the environment.
    backends: list[BackendConfig] = Field(
        default_factory=lambda: [BackendConfig(id="claude", type="claude_cli")]
    )
    #: Per-workflow-step backend assignment (step name -> backend id).
    #: File-only; steps not listed use the step's default backend.
    step_backends: dict[str, str] = {}
    #: Backend used for ad-hoc ``/api/sessions`` dispatch. File-only.
    default_session_backend: str = "claude"

    @model_validator(mode="after")
    def _apply_backends_file(self) -> Settings:
        """Overlay backend config from ``backends_file`` when set.

        The file owns ``backends`` / ``step_backends`` /
        ``default_session_backend``; any it omits keeps its default
        value. A missing or malformed file fails fast at startup.
        """
        if not self.backends_file:
            return self
        path = Path(self.backends_file)
        if not path.is_file():
            raise ValueError(f"backends_file not found: {path}")
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"invalid TOML in {path}: {exc}") from exc
        if "backends" in data:
            self.backends = [
                BackendConfig(**entry) for entry in data["backends"]
            ]
        if "step_backends" in data:
            self.step_backends = dict(data["step_backends"])
        if "default_session_backend" in data:
            self.default_session_backend = data["default_session_backend"]
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()

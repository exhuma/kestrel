"""Application configuration via pydantic-settings."""
from __future__ import annotations

import logging
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from app.config_models import BackendConfig, TaskSourceConfig

_log = logging.getLogger("kestrel.config")

# Backend config is file-only: these keys are resolved from the TOML file
# named by ``KESTREL_CONFIG_FILE`` (or left at their claude-only defaults),
# never from the environment. Filtered out of the env/dotenv sources below.
_FILE_ONLY_FIELDS = frozenset(
    {"backends", "step_backends", "default_session_backend", "task_sources"}
)

# Applicative (non-secret) settings the TOML config file may override. Unlike
# the file-only backend keys, these remain readable from the environment too
# (back-compat); the file simply wins when it sets them. Secrets
# (tokens/passwords) are deliberately excluded — those stay in the env.
_CONFIG_FILE_FIELDS = frozenset(
    {
        "poll_interval_seconds",
        "verify_checks",
        "max_verify_iterations",
    }
)


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

        Backends are configured exclusively via ``KESTREL_CONFIG_FILE``
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
    #: Uvicorn bind address / port and the dev auto-reload toggle
    #: (``KESTREL_HOST`` / ``KESTREL_PORT`` / ``KESTREL_RELOAD``). Sourced
    #: through Settings so a ``backend/.env`` value is honoured.
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
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
    #: Enable OpenTelemetry tracing (``KESTREL_OTEL_ENABLED``). Off by
    #: default: a personal localhost tool pays nothing until a collector is
    #: configured. When true, spans export over OTLP to
    #: ``OTEL_EXPORTER_OTLP_ENDPOINT`` and log records gain ``trace_id`` /
    #: ``span_id`` (see :mod:`app.telemetry` and ``module-opentelemetry``).
    otel_enabled: bool = False
    #: ``service.name`` reported on exported spans
    #: (``KESTREL_OTEL_SERVICE_NAME``). Defaults to ``kestrel``.
    otel_service_name: str = "kestrel"
    #: Path to the TOML config file (``KESTREL_CONFIG_FILE``). Holds the
    #: backend config (``backends`` / ``step_backends`` /
    #: ``default_session_backend``) and applicative overrides (see
    #: ``_CONFIG_FILE_FIELDS``: ``watched_repos``, ``trigger_label``, …).
    #: Secrets stay in the environment. Mount it as a volume in Docker;
    #: relative paths resolve against the working directory.
    config_file: str = ""
    #: Deprecated alias for ``config_file`` (``KESTREL_BACKENDS_FILE``);
    #: honoured only when ``config_file`` is unset, with a warning.
    backends_file: str = ""
    #: Dispatchable agent backends. File-only (see ``_FILE_ONLY_FIELDS``):
    #: resolved from ``backends_file`` or left at this claude-only default,
    #: never from the environment.
    backends: list[BackendConfig] = Field(
        default_factory=lambda: [BackendConfig(id="claude", type="claude_cli")]
    )
    #: Per-workflow-step backend assignment (step name -> backend id).
    #: File-only; steps not listed use the step's default backend. Sub-step
    #: keys (e.g. ``refine.reconcile``) route a single refine sub-agent to
    #: its own backend, falling back to the ``refine`` step's backend.
    step_backends: dict[str, str] = {}
    #: Backend used for ad-hoc ``/api/sessions`` dispatch. File-only.
    default_session_backend: str = "claude"
    #: Refinement robustness knobs (help on cheaper/local models; all
    #: default to today's behaviour). ``refine_samples`` runs the
    #: coordinator and generators N times and unions the result to reduce
    #: variance; ``refine_critic`` adds an adversarial completeness pass
    #: after reconciliation; ``reconcile_mode`` selects how aggressively
    #: questions are consolidated: ``rewrite`` (LLM consolidating
    #: rewriter), ``dedup`` (coverage-safe within-audience duplicate
    #: removal, no LLM), or ``off`` (keep the pooled questions as-is).
    refine_samples: int = 1
    refine_critic: bool = False
    reconcile_mode: Literal["rewrite", "dedup", "off"] = "rewrite"
    #: Safety net (``KESTREL_ALLOW_INCOMPLETE_ANSWERS``): when true, a
    #: questionnaire may be submitted with required questions left
    #: unanswered (sent blank). Provided answers are still validated for
    #: well-formedness. Off by default.
    allow_incomplete_answers: bool = False
    #: GitHub ingestion (feature 002). The webhook HMAC shared secret
    #: (``KESTREL_WEBHOOK_SECRET``): the authenticity gate for the one
    #: off-loopback endpoint (constitution v1.2.0). Never logged.
    webhook_secret: str = ""
    #: Configured task sources (GitHub / Jira). File-only (like ``backends``);
    #: each entry declares a ``type`` and that source's selection criteria.
    #: See :class:`app.config_models.TaskSourceConfig`.
    task_sources: list[TaskSourceConfig] = []
    #: Single cadence (seconds) governing every source's re-check loop — the
    #: GitHub reconcile backstop and the Jira poll alike.
    poll_interval_seconds: int = 300
    #: Public base URL of the kestrel web UI, used to build gate-notification
    #: deep-links (``KESTREL_PUBLIC_BASE_URL``). Unset ⇒ comments post without
    #: a link. Operator-exposed, same posture as the webhook endpoint.
    public_base_url: str = ""
    #: Jira API token / PAT (``KESTREL_JIRA_API_TOKEN``). Secret; never logged.
    #: The default token env var for a ``jira`` task source.
    jira_api_token: str = ""
    #: Shell commands run in the run's worktree as verify evidence (v1).
    #: JSON list, e.g. ``["uv run pytest -q"]``. Empty ⇒ judgment-only.
    verify_checks: list[str] = []
    #: Max code↔verify iterations before the loop escalates (feature 003).
    max_verify_iterations: int = 3

    def github_sources(self) -> list[TaskSourceConfig]:
        """The configured GitHub task sources."""
        return [s for s in self.task_sources if s.type == "github"]

    def jira_sources(self) -> list[TaskSourceConfig]:
        """The configured Jira task sources."""
        return [s for s in self.task_sources if s.type == "jira"]

    def github_source_for(self, repo: str) -> TaskSourceConfig | None:
        """The GitHub source whose allow-list has ``repo`` (first match)."""
        for source in self.github_sources():
            if repo in source.watched_repos:
                return source
        return None

    @model_validator(mode="after")
    def _apply_config_file(self) -> Settings:
        """Overlay config from the TOML file when one is set.

        The file owns the backend keys (``backends`` / ``step_backends`` /
        ``default_session_backend``) and may override the applicative keys
        in ``_CONFIG_FILE_FIELDS`` (``watched_repos`` etc.); anything it
        omits keeps its env/default value, so the file wins only where it
        speaks. Prefers ``config_file``; ``backends_file`` is a deprecated
        alias honoured with a warning. A missing or malformed file fails
        fast at startup. Defined before the completeness-warning validators
        (after-validators run in definition order) so they see the file's
        final values.
        """
        path_str = self.config_file
        if not path_str:
            if not self.backends_file:
                return self
            _log.warning(
                "KESTREL_BACKENDS_FILE is deprecated; use KESTREL_CONFIG_FILE."
            )
            path_str = self.backends_file
        path = Path(path_str)
        if not path.is_file():
            raise ValueError(f"config_file not found: {path}")
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
        if "task_sources" in data:
            self.task_sources = [
                TaskSourceConfig(**entry) for entry in data["task_sources"]
            ]
        # Applicative overrides: file wins, but only for keys it sets.
        for key in _CONFIG_FILE_FIELDS:
            if key in data:
                setattr(self, key, data[key])
        return self

    @model_validator(mode="after")
    def _warn_incomplete_ingestion_config(self) -> Settings:
        """Warn (not fail) when GitHub sources are set without a secret.

        Ingestion silently doing nothing is a worse failure mode than a
        startup warning, so surface the likely misconfiguration.
        """
        if self.github_sources() and not self.webhook_secret:
            _log.warning(
                "a github task source is configured but webhook_secret is "
                "empty; webhook ingestion will reject every delivery until "
                "KESTREL_WEBHOOK_SECRET is configured."
            )
        return self

    @model_validator(mode="after")
    def _warn_incomplete_source_config(self) -> Settings:
        """Warn (not fail) when a Jira source can't authenticate or reach code.

        A source silently doing nothing is a worse failure mode than a startup
        warning, so surface the likely misconfiguration per source.
        """
        for source in self.jira_sources():
            if not source.token():
                _log.warning(
                    "jira task source %r has no token (env %r unset); its "
                    "polling cannot authenticate.",
                    source.base_url,
                    source.token_env or "KESTREL_JIRA_API_TOKEN",
                )
            if source.code_host in ("gitlab", "gitea") and not (
                source.code_host_base_url and source.code_host_token()
            ):
                _log.warning(
                    "jira task source %r uses code_host %r but its base URL or "
                    "token is empty; resolved repos cannot be reached.",
                    source.base_url,
                    source.code_host,
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()

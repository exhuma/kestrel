"""Application configuration via pydantic-settings."""
from __future__ import annotations

import logging
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

_log = logging.getLogger("kestrel.config")

# Backend config is file-only: these keys are resolved from the TOML file
# named by ``KESTREL_CONFIG_FILE`` (or left at their claude-only defaults),
# never from the environment. Filtered out of the env/dotenv sources below.
_FILE_ONLY_FIELDS = frozenset(
    {"backends", "step_backends", "default_session_backend"}
)

# Applicative (non-secret) settings the TOML config file may override. Unlike
# the file-only backend keys, these remain readable from the environment too
# (back-compat); the file simply wins when it sets them. Secrets
# (tokens/passwords) are deliberately excluded — those stay in the env.
_CONFIG_FILE_FIELDS = frozenset(
    {
        "watched_repos",
        "trigger_label",
        "reconcile_interval_seconds",
        "verify_checks",
        "max_verify_iterations",
    }
)


def _normalize_watched_repos(v: object) -> object:
    """Accept a JSON list or a comma-separated string of repos.

    Shared by the ``watched_repos`` field validator (env/dotenv values,
    always strings) and the TOML overlay (a native array needs no work,
    but a string value is still tolerated).
    """
    if v is None or v == "":
        return []
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            import json

            return json.loads(s)
        return [item.strip() for item in s.split(",") if item.strip()]
    return v


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
    #: Allow-list of ``owner/name`` repos kestrel may ingest from and
    #: reconcile against (``KESTREL_WATCHED_REPOS``). Accepts a JSON list
    #: or a comma-separated string; anything outside the list is ignored.
    watched_repos: Annotated[list[str], NoDecode] = []
    #: The issue label that flags an issue for ingestion.
    trigger_label: str = "kestrel"
    #: Reconciliation cadence in seconds
    #: (``KESTREL_RECONCILE_INTERVAL_SECONDS``).
    reconcile_interval_seconds: int = 300
    #: Public base URL of the kestrel web UI, used to build gate-notification
    #: deep-links (``KESTREL_PUBLIC_BASE_URL``). Unset ⇒ comments post without
    #: a link. Operator-exposed, same posture as the webhook endpoint.
    public_base_url: str = ""
    #: Jira ingestion (feature 003). Base URL of the Jira instance
    #: (``KESTREL_JIRA_BASE_URL``); empty ⇒ Jira polling disabled.
    jira_base_url: str = ""
    #: Jira auth mode: ``basic`` (Cloud — email + API token) or ``bearer``
    #: (Server/DC — personal access token).
    jira_auth: Literal["basic", "bearer"] = "basic"
    #: Basic-auth username (Jira Cloud email); used when ``jira_auth`` is
    #: ``basic``.
    jira_email: str = ""
    #: Jira API token / PAT (``KESTREL_JIRA_API_TOKEN``). Secret; never logged.
    jira_api_token: str = ""
    #: RFC project key polled for change requests (required to poll).
    jira_project: str = ""
    #: Extra JQL AND-ed onto ``project = "<key>"`` (e.g. ``status = "Ready"``).
    #: Keeps kestrel agnostic of company-internal workflow states.
    jira_jql_filter: str = ""
    #: Field id/name on the RFC holding the target ``owner/name[@base_branch]``.
    jira_repo_field: str = ""
    #: Jira poll cadence in seconds.
    jira_poll_interval_seconds: int = 300
    #: Code host for Jira-resolved repos: ``github`` | ``gitlab`` | ``gitea``.
    #: Self-hostable — ``gitlab``/``gitea`` point at an on-prem instance.
    code_host: Literal["github", "gitlab", "gitea"] = "github"
    #: Self-hosted code-host instance base URL (e.g. ``https://gitlab.local``).
    code_host_base_url: str = ""
    #: Code-host token / PAT. Secret; never logged. Falls back to
    #: ``github_token`` when ``code_host`` is ``github``.
    code_host_token: str = ""
    #: Shell commands run in the run's worktree as verify evidence (v1).
    #: JSON list, e.g. ``["uv run pytest -q"]``. Empty ⇒ judgment-only.
    verify_checks: list[str] = []
    #: Max code↔verify iterations before the loop escalates (feature 003).
    max_verify_iterations: int = 3

    @field_validator("watched_repos", mode="before")
    @classmethod
    def _parse_watched_repos(cls, v: object) -> object:
        """Accept a JSON list or a comma-separated string of repos."""
        return _normalize_watched_repos(v)

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
        # Applicative overrides: file wins, but only for keys it sets.
        if "watched_repos" in data:
            self.watched_repos = _normalize_watched_repos(
                data["watched_repos"]
            )
        for key in _CONFIG_FILE_FIELDS - {"watched_repos"}:
            if key in data:
                setattr(self, key, data[key])
        return self

    @model_validator(mode="after")
    def _warn_incomplete_ingestion_config(self) -> Settings:
        """Warn (not fail) when watched repos are set without a secret.

        Ingestion silently doing nothing is a worse failure mode than a
        startup warning, so surface the likely misconfiguration.
        """
        if self.watched_repos and not self.webhook_secret:
            _log.warning(
                "watched_repos is set but webhook_secret is empty; "
                "webhook ingestion will reject every delivery until "
                "KESTREL_WEBHOOK_SECRET is configured."
            )
        return self

    @model_validator(mode="after")
    def _warn_incomplete_jira_config(self) -> Settings:
        """Warn (not fail) when Jira is half-configured.

        Jira polling silently doing nothing is a worse failure mode than a
        startup warning, so surface the likely misconfiguration.
        """
        if self.jira_base_url and not (
            self.jira_project and self.jira_api_token
        ):
            _log.warning(
                "jira_base_url is set but jira_project or jira_api_token is "
                "empty; Jira polling will not start until both are configured."
            )
        return self

    @model_validator(mode="after")
    def _warn_incomplete_code_host_config(self) -> Settings:
        """Warn when a self-hosted code host lacks its URL or token."""
        if self.code_host in ("gitlab", "gitea") and not (
            self.code_host_base_url and self.code_host_token
        ):
            _log.warning(
                "code_host is %r but code_host_base_url or code_host_token is "
                "empty; Jira-resolved repositories cannot be reached until "
                "both are configured.",
                self.code_host,
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()

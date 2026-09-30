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

from app.config_models import BackendConfig, TaskSourceConfig, TranslationConfig

_log = logging.getLogger("kestrel.config")

# Backend config is file-only: these keys are resolved from the TOML file
# named by ``KESTREL_CONFIG_FILE`` (or left at their claude-only defaults),
# never from the environment. Filtered out of the env/dotenv sources below.
_FILE_ONLY_FIELDS = frozenset(
    {
        "backends",
        "default_session_backend",
        "task_sources",
        "translation",
    }
)

# Applicative (non-secret) settings the TOML config file may override. Unlike
# the file-only backend keys, these remain readable from the environment too
# (back-compat); the file simply wins when it sets them. Secrets
# (tokens/passwords) are deliberately excluded — those stay in the env.
_CONFIG_FILE_FIELDS = frozenset(
    {
        "poll_interval_seconds",
        "max_verify_iterations",
        "max_ci_repair_iterations",
        "port",
        "database_url",
        "workspace_root",
        "screenshots_root",
        "board_artifacts_root",
        "comment_sentinel_enabled",
        "comment_sentinel",
        "specialists_root",
        "board_input_max_bytes",
        "board_input_security_timeout_seconds",
        "board_turn_timeout_seconds",
        "board_claim_lease_seconds",
        "board_workspace_lease_seconds",
        "board_max_parallel_read_cards",
        "board_recovery_interval_seconds",
        "board_ci_poll_interval_seconds",
        "board_cab1_interview_max_questions",
        "board_unreadable_retry_cap",
        "health_check_interval_seconds",
        "health_check_timeout_seconds",
        "board_dev_actions_enabled",
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
    #: Durable directory holding workflow screenshots after a run's worktree
    #: is torn down (see ``services/workflows/screenshots.py``). Keyed by run
    #: id; in Docker point this at the ``/data`` volume so shots survive.
    screenshots_root: str = "./.kestrel-screenshots"
    #: Durable, content-addressed store for handoff-artifact bodies
    #: (feature 026, FR-013). Keyed by content hash, so recovery after
    #: restart can always re-read a card's output.
    board_artifacts_root: str = "./.kestrel-board-artifacts"
    permission_mode: str = "acceptEdits"
    # Directory of the built SPA to serve. Empty (dev default) means the
    # backend is API-only and the SPA is served by the Vite dev server; the
    # container image sets this to the baked-in static bundle.
    static_dir: str = ""
    github_token: str = ""
    github_api_base: str = "https://api.github.com"
    git_base: str = "https://github.com"
    database_url: str = "sqlite:///./kestrel.db"
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
    #: backend config (``backends`` / ``default_session_backend``) and
    #: applicative overrides (see
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
    #: Capture UI mockups during a uiux refine round
    #: (``KESTREL_MOCKUPS_ENABLED``). Off by default — not yet well
    #: implemented, per manual-testing feedback on feature 012.
    mockups_enabled: bool = False
    #: Safety net (``KESTREL_ALLOW_INCOMPLETE_ANSWERS``): when true, a
    #: questionnaire may be submitted with required questions left
    #: unanswered (sent blank). Provided answers are still validated for
    #: well-formedness. Off by default.
    allow_incomplete_answers: bool = False
    #: GitHub ingestion (feature 002). The webhook HMAC shared secret
    #: (``KESTREL_WEBHOOK_SECRET``): the authenticity gate for the one
    #: off-loopback endpoint (constitution v1.2.0). Never logged.
    webhook_secret: str = ""
    #: Configured task sources (GitHub / Jira / local). File-only (like
    #: each entry declares a ``type`` and that source's selection criteria.
    #: See :class:`app.config_models.TaskSourceConfig`.
    task_sources: list[TaskSourceConfig] = []
    #: Dedicated, stateless translation backing service. File-only so it cannot
    #: be confused with a workflow backend; secrets remain env-backed.
    translation: TranslationConfig | None = None
    #: Single cadence (seconds) governing every source's re-check loop — the
    #: GitHub reconcile backstop and the Jira poll alike.
    poll_interval_seconds: int = 300
    #: Cadence (seconds) for the background source-health check cycle
    #: (feature 014) — deliberately independent of, and much shorter
    #: than, ``poll_interval_seconds``: health is a much cheaper check
    #: and its whole value is fast diagnostic feedback.
    health_check_interval_seconds: int = 60
    #: Per-adapter timeout (seconds) for one health check (feature 014):
    #: bounds a single unresponsive integration so it cannot stall the
    #: rest of the cycle.
    health_check_timeout_seconds: int = 10
    #: Public base URL of the kestrel web UI, used to build gate-notification
    #: deep-links (``KESTREL_PUBLIC_BASE_URL``). Unset ⇒ comments post without
    #: a link. Operator-exposed, same posture as the webhook endpoint.
    public_base_url: str = ""
    #: Jira API token / PAT (``KESTREL_JIRA_API_TOKEN``). Secret; never logged.
    #: The default token env var for a ``jira`` task source.
    jira_api_token: str = ""
    #: Max verification rounds for one approved CAB-2 task before a
    #: non-clean result escalates to coordinator review (feature 031; the
    #: same knob feature 003's fixed driver used for its code↔verify loop).
    max_verify_iterations: int = 3
    #: Independent cap for repair attempts triggered by required CI failures.
    max_ci_repair_iterations: int = Field(default=2, ge=0)
    #: Debug the code↔verify dialogue (``KESTREL_WORKFLOW_DEBUG``). When on,
    #: every prompt/result exchanged between the coder and the verifier is
    #: appended to a plain-text transcript next to the run's worktree, and
    #: the worktree is never auto-deleted (done/escalated/failed) so both
    #: stay inspectable — only an explicit abandon still removes them. Off
    #: by default: a personal tool should not silently accumulate worktrees.
    workflow_debug: bool = False
    #: Trigger token a ticket comment or PR review must contain, whole-token
    #: and case-insensitive, for kestrel to act on it at all (feature 013,
    #: ``KESTREL_FEEDBACK_MARKER``). Unmarked feedback is never even
    #: recorded — the primary self-triggering-loop guard (constitution's
    #: recorded self-feedback-loop risk).
    feedback_marker: str = "@kestrel"
    #: Mark every Kestrel-authored comment (``KESTREL_COMMENT_SENTINEL``).
    #: Intake rejects a marked comment before it can affect a gate, which is
    #: necessary while Kestrel posts through an operator's personal account.
    comment_sentinel: str = "[kestrel:posted]"
    #: Disable comment marking only for an explicitly incompatible source.
    #: ``False`` also disables sentinel-based intake filtering.
    comment_sentinel_enabled: bool = True
    #: Authors whose marked feedback is still discarded before it reaches
    #: persistence (feature 013) — the second independent self-loop guard,
    #: alongside GitHub's ``user.type == "Bot"`` detection. Empty by
    #: default; an operator adds kestrel's own configured identity here if
    #: it ever posts comments as an authenticated user rather than a bot.
    feedback_ignore_authors: list[str] = []
    #: How many days after a run goes terminal (done/failed/rejected/
    #: escalated/decomposed) ``FeedbackPollService`` keeps re-polling it
    #: for review/ticket feedback (feature 013), rather than polling every
    #: finished run forever. A run still non-terminal is always polled
    #: regardless of this setting.
    feedback_window_days: int = 14
    #: Root directory of file-backed specialist definitions (feature 026,
    #: ``KESTREL_SPECIALISTS_ROOT``): one subdirectory per named role, each
    #: holding a manifest and prompt file. Relative paths resolve against the
    #: working directory; the board's specialist loader (see
    #: ``services/board/specialists.py``) treats this as a trust boundary and
    #: refuses to load a manifest that resolves outside it.
    specialists_root: str = "./specialists"
    #: Maximum size in bytes of one untrusted board input (task body,
    #: feedback item, gate/questionnaire answer, or direct session prompt)
    #: accepted before board intake (feature 026,
    #: ``KESTREL_BOARD_INPUT_MAX_BYTES``). Oversized input is quarantined
    #: rather than truncated, so no partial untrusted content is ever used.
    board_input_max_bytes: int = Field(default=65536, gt=0)
    #: Timeout in seconds for the input-security specialist's classification
    #: call (feature 026, ``KESTREL_BOARD_INPUT_SECURITY_TIMEOUT_SECONDS``). A
    #: timeout is treated as a malformed result and fails closed into
    #: quarantine.
    board_input_security_timeout_seconds: float = Field(default=30.0, gt=0)
    #: Timeout in seconds for one agent turn on the board — the
    #: coordinator's, or any specialist's on a card
    #: (``KESTREL_BOARD_TURN_TIMEOUT_SECONDS``). Separate from the input-
    #: security timeout: a coder's turn legitimately runs for minutes,
    #: and a slow local model needs far more than a classification does.
    #: Defaults to the claim lease, past which recovery would reclaim the
    #: card anyway.
    board_turn_timeout_seconds: float = Field(default=600.0, gt=0)
    #: How long a card claim lease is held before it is considered abandoned
    #: and eligible for recovery (feature 026,
    #: ``KESTREL_BOARD_CLAIM_LEASE_SECONDS``).
    board_claim_lease_seconds: int = Field(default=600, gt=0)
    #: How long a repository workspace-write lease is held before recovery
    #: may reclaim it (feature 026, ``KESTREL_BOARD_WORKSPACE_LEASE_SECONDS``).
    board_workspace_lease_seconds: int = Field(default=1800, gt=0)
    #: Maximum number of read-only board cards that may be claimed and
    #: active at once across the whole process (feature 026,
    #: ``KESTREL_BOARD_MAX_PARALLEL_READ_CARDS``).
    board_max_parallel_read_cards: int = Field(default=4, gt=0)
    #: How many times a card whose result cannot be read (malformed
    #: JSON, a missing block) is tried again on its own before it is
    #: escalated to the coordinator (feature 042,
    #: ``KESTREL_BOARD_UNREADABLE_RETRY_CAP``). ``0`` escalates at once.
    board_unreadable_retry_cap: int = Field(default=1, ge=0)
    #: How often the recovery sweep checks for expired claim leases
    #: (feature 026, ``KESTREL_BOARD_RECOVERY_INTERVAL_SECONDS``).
    board_recovery_interval_seconds: float = Field(default=60.0, gt=0)
    #: How often the CI-poll sweep checks each delivered workflow's
    #: required CI status (feature 026, T052,
    #: ``KESTREL_BOARD_CI_POLL_INTERVAL_SECONDS``). Only matters for a
    #: source/repo with ``required_ci_statuses`` configured — a workflow
    #: with none configured is never polled regardless.
    board_ci_poll_interval_seconds: float = Field(default=60.0, gt=0)
    #: The strategic-fit interview's hard question cap (feature 027,
    #: ``KESTREL_BOARD_CAB1_INTERVIEW_MAX_QUESTIONS``) — keeps the
    #: pre-CAB-1 interview light, unlike the deeper post-approval
    #: refinement interviews it precedes.
    board_cab1_interview_max_questions: int = Field(default=3, gt=0)
    #: Max refinement-interview rounds per persona per workflow (feature
    #: 028, ``KESTREL_BOARD_REFINEMENT_ROUND_CAP``). ``1`` (the default)
    #: is today's exact behavior — one round per persona, no follow-up.
    #: Above ``1``, a persona whose answers leave genuine ambiguity gets
    #: a further round, up to this cap, before PRD drafting starts.
    board_refinement_round_cap: int = Field(default=1, ge=1)
    #: Max PRD redraft attempts per workflow after a ``prd_gate``
    #: rejection (feature 028, ``KESTREL_BOARD_PRD_REDRAFT_CAP``). ``1``
    #: (the default) allows exactly one redraft per rejection, matching
    #: today's single-redraft behavior; a further rejection past the cap
    #: escalates to the operator instead of redrafting again.
    board_prd_redraft_cap: int = Field(default=1, ge=1)
    #: Max redrafts of `pm`'s restatement after the operator rejects the
    #: understanding (feature 032, ``KESTREL_BOARD_UNDERSTANDING_REDRAFT_CAP``).
    #: A further rejection past the cap opens a coordinator review instead
    #: of another redraft. ``0`` never redrafts.
    board_understanding_redraft_cap: int = Field(default=2, ge=0)
    #: Enable the ``/api/board/workflows/{id}/dev/*`` cleanup/rerun
    #: endpoints (feature 026, T069,
    #: ``KESTREL_BOARD_DEV_ACTIONS_ENABLED``). Off by default —
    #: **temporary, dev-only**: lets a local-task-source dry run be
    #: repeated without restarting kestrel or hand-editing the database.
    #: Restricted at call time to a workflow whose source is ``private``
    #: regardless of this flag. Meant to be deleted, not hardened, once
    #: the board is production-ready — see
    #: ``app/services/board/dev_reset.py``'s module docstring.
    board_dev_actions_enabled: bool = False

    def github_sources(self) -> list[TaskSourceConfig]:
        """The configured GitHub task sources."""
        return [s for s in self.task_sources if s.type == "github"]

    def jira_sources(self) -> list[TaskSourceConfig]:
        """The configured Jira task sources."""
        return [s for s in self.task_sources if s.type == "jira"]

    def local_sources(self) -> list[TaskSourceConfig]:
        """Return the configured local task sources."""
        return [
            source for source in self.task_sources if source.type == "local"
        ]

    def github_source_for(self, repo: str) -> TaskSourceConfig | None:
        """The GitHub source whose allow-list has ``repo`` (first match)."""
        for source in self.github_sources():
            if repo in source.watched_repos:
                return source
        return None

    def required_ci_statuses_for(self, source: str, repo: str) -> list[str]:
        """Return the configured required CI checks for a run's source."""
        if source == "github-issue":
            config = self.github_source_for(repo)
            return config.required_ci_statuses if config else []
        if source == "jira-issue" and self.jira_sources():
            return self.jira_sources()[0].required_ci_statuses
        return []

    @model_validator(mode="after")
    def _apply_config_file(self) -> Settings:
        """Overlay config from the TOML file when one is set.

        The file owns the backend keys (``backends`` /
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
                _log.info(
                    "no config file configured (KESTREL_CONFIG_FILE/"
                    "KESTREL_BACKENDS_FILE unset) — using built-in defaults"
                )
                return self
            _log.warning(
                "KESTREL_BACKENDS_FILE is deprecated; use KESTREL_CONFIG_FILE."
            )
            path_str = self.backends_file
        path = Path(path_str)
        if not path.is_file():
            raise ValueError(f"config_file not found: {path}")
        _log.info("loading config file: %s", path.resolve())
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"invalid TOML in {path}: {exc}") from exc
        if "backends" in data:
            self.backends = [
                BackendConfig(**entry) for entry in data["backends"]
            ]
        if "default_session_backend" in data:
            self.default_session_backend = data["default_session_backend"]
        if "task_sources" in data:
            self.task_sources = [
                TaskSourceConfig(**entry) for entry in data["task_sources"]
            ]
        if "translation" in data:
            self.translation = TranslationConfig(**data["translation"])
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

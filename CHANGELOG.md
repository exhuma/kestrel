# Changelog

All notable changes to kestrel are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
uses [CalVer](docs/releasing.md) (`vYYYY.M.D` with a pre-release suffix).

## [Unreleased]

The slim-core work package (#90): kestrel is the engine, the task source
holds the record. Constitution 2.0.0.

### Breaking

- **PostgreSQL replaces SQLite.** `KESTREL_DATABASE_URL` is required
  (`postgresql+psycopg://user:password@host:5432/kestrel`); kestrel does not
  start without it. The schema is one fresh baseline migration: existing
  SQLite databases are not migrated. The image no longer sets a database
  URL; `docker-compose.yml` brings a `postgres` service.
- **Ad-hoc sessions are gone.** The sessions view, `/api/sessions*`,
  `/api/backends*` and the `session`/`event` tables are removed. Work enters
  kestrel only through a task source. Agent output goes to the server log
  (`kestrel.agent`), tagged with the session id; each card attempt records
  its session id. See `docs/observability.md`.
- **`config.toml` accepts every setting**, and an unknown top-level key now
  fails at startup. Remove keys of deleted settings from existing files.
  Explicit `Settings(...)` arguments now rank above the file.
- **Removed settings:** `refine_samples`, `refine_critic`, `reconcile_mode`,
  `mockups_enabled`, `allow_incomplete_answers`, `workflow_debug`,
  `KESTREL_RELOAD` (use `python -m app --reload`), `KESTREL_BACKENDS_FILE`,
  `board_dev_actions_enabled`, `board_workspace_lease_seconds`,
  `board_artifacts_root` (`KESTREL_BOARD_ARTIFACTS_ROOT`), the Jira
  `transition_failed` / `transition_escalated` / `transition_rejected` ids,
  the per-source `hooks_dir`, the `translation` section, and the Jira
  source `key`.
- **Removed:** operator hooks, the `openai_compat` backend and translation,
  the notification centre, issue dismissals, the dev reset/rerun actions,
  the legacy `?run=` deep link, and API endpoints nothing called.
- **`default_session_backend` is now `default_backend`** in `config.toml`
  (there are no sessions any more). An old key fails at startup.
- **Permission modes are backend-neutral:** `KESTREL_PERMISSION_MODE` takes
  `read_only` or `edit` (default `edit`); the Claude backend maps them to its
  own flags.

### Fixed

- Races that SQLite's single writer hid are now atomic on PostgreSQL:
  claims and repository leases, workflow revision and CI status counters,
  gate decisions, quarantine review resolution, card state moves, and
  comment cursors. A result arriving while recovery frees its claim no
  longer both completes and resets the card.
- GitHub clients are closed on shutdown; error messages keep a bounded part
  of the response body.

### Changed

- Artifact bodies live in PostgreSQL instead of files under
  `/data/board-artifacts`. The repository lease is part of the claim lease
  (one table), and coordinator actions are board events (no separate
  table).

- The constitution is 2.0.0: state placement (business records live in the
  task source and the code host), a single operator with many participants,
  PostgreSQL, OIDC sign-in planned for the operator, and the interview form
  as a second public exception.
- Tests run against a throw-away PostgreSQL database
  (`KESTREL_TEST_DATABASE_URL`); integration tests carry
  `pytest.mark.integration`.

## [2026.7.5-alpha.3] - 2026-07-05

### Added

- GitHub repository link in the header, shown when `VITE_GITHUB_REPO_URL` is
  set at build time (hidden otherwise).
- Refined-issue and implementation-plan deliverables now render as HTML
  (Markdown) at a readable prose width instead of raw monospace text.
- Per-question questionnaire controls: a "none of these fit" correction that
  instructs the agent, and an optional "additional information" note on every
  question.
- Live workflow feedback: per-specialist activity words on the session chips
  (thinking / reading / responding …), the current refine round and cap, and
  the backend handling each step. OpenAI-compatible backends now stream turns
  to drive this.
- Refine robustness for weak/local models: multi-sample ensembling, reconcile
  modes, and an optional critic pass.
- Failed refine specialists (timeout, crash, empty response) are surfaced at
  the review gate and automatically retried on submit — capped per specialist
  (soft → hard) with a round cap that grows per retry.
- `KESTREL_ALLOW_INCOMPLETE_ANSWERS` safety net to submit a questionnaire with
  required questions still unanswered.

### Changed

- Abandoning a workflow now cleans up all of its attributed sessions and local
  repository clones, with a warning in the confirm dialog.

### Fixed

- Option-less select questions are coerced to free text — both at generation
  and on load — so they are always answerable; previously such answers never
  registered and the submit button stayed disabled.
- The raw questionnaire JSON no longer flashes on screen after answers are
  submitted while the coordinator re-runs.
- Aggregated questions are given unique ids, so answers no longer collide
  across specialists.
- Application logs now appear under unified logging when launched via
  `uvicorn app.main:app`, not only via `python -m app`.
- An agent turn that errors now fails loudly instead of silently surfacing the
  error text as a deliverable.
- The workflow-detail API no longer loads the session store to label each
  step's backend, so a read never depends on the session subsystem (and cannot
  fail on a freshly-migrated database).

## [2026.7.5-alpha.1] - 2026-07-05

### Added

- `GET /healthz` now reports the running image version and verifies database
  readiness (HTTP 503 when the database is unreachable).
- Compose-level healthcheck and `host.docker.internal` mapping so host-run
  backends (Ollama, `opencode serve`) are reachable from the container.
- Unified logging: uvicorn and application logs share one stdout stream, with
  `KESTREL_LOG_FORMAT` (`text` default, or `json` for one document per line)
  and `KESTREL_LOG_LEVEL`. Launch via `python -m app`.
- Audience-split documentation under `docs/` (getting started, configuration,
  backends, troubleshooting, development, observability, architecture,
  releasing).

### Changed

- Backends are configured **only** via `KESTREL_BACKENDS_FILE` (or the
  `backends.toml` it names). The `KESTREL_BACKENDS`,
  `KESTREL_STEP_BACKENDS`, and `KESTREL_DEFAULT_SESSION_BACKEND` environment
  variables are no longer read.

## [2026.7.3-alpha.1] - 2026-07-03

First alpha. A single-user web tool to dispatch and monitor coding-agent
sessions.

### Added

- **Docker image** bundling the FastAPI backend, the built Vue/Vuetify SPA,
  and the `claude` CLI; serves the UI and API on port 8000.
- **Claude Code dispatch** — spawns `claude` sessions in per-run git
  workspaces and streams events over SSE to the UI. Host Claude login,
  MCP servers, and plugins are reused via read-only seed mounts.
- **Pluggable backends** — dispatch to `opencode` (via `opencode serve`) or a
  self-hosted OpenAI-compatible LLM, configured from a TOML file
  (`KESTREL_BACKENDS_FILE`), with per-workflow-step assignment and capability
  checking.
- **GitHub issue → PR workflow** — refine, clarify, plan, and implement with
  human approval gates; persisted to SQLite and resumable.
- **CalVer release pipeline** — tag-driven GHCR publish with cascading
  channel tags (`alpha`/`beta`/`rc`/`stable`) and no `latest`.

[Unreleased]: https://github.com/exhuma/kestrel/compare/v2026.7.5-alpha.1...HEAD
[2026.7.5-alpha.1]: https://github.com/exhuma/kestrel/compare/v2026.7.3-alpha.1...v2026.7.5-alpha.1
[2026.7.3-alpha.1]: https://github.com/exhuma/kestrel/releases/tag/v2026.7.3-alpha.1

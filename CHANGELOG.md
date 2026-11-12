# Changelog

All notable changes to kestrel are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
uses [CalVer](docs/releasing.md) (`vYYYY.M.D` with a pre-release suffix).

## [Unreleased]

The slim-core work package (#90): kestrel is the engine, the task source
holds the record. Constitution 2.0.0.

### Breaking

- **Approved tasks wait to be handed to kestrel (#99).** On Jira, nothing
  starts when CAB-2 approves the plan. Kestrel starts a task once its work
  item is assigned to the account behind the source's token, or matches the
  new `work_items_jql`. A task a person finishes (its item's status is
  Done) counts as complete without running, and the tasks after it start.
  When an item kestrel was working on is given back to a person, kestrel
  stops that task, notes its branch on the item, and asks the change owner
  how to go on instead of delivering part of the request. GitHub and local
  tasks still start at once. Kestrel's own manual-task cards, the "Mark
  done" action and the "manual tasks assigned to you" count are removed:
  a person's task lives on its work item. New setting:
  `board_handover_poll_interval_seconds`.
- **Turns run while the agent works, not for a fixed time.**
  `board_turn_timeout_seconds` and a backend's `timeout` are removed. A turn
  is stopped after `board_turn_idle_seconds` without activity (default 15
  minutes) or `board_turn_max_seconds` in all (default six hours), so long
  coding turns no longer need a global timeout of hours. A failed turn frees
  its card at once instead of when its lease expires, and a running turn's
  claim is renewed, so `board_claim_lease_seconds` only decides how soon a
  card is recovered after kestrel itself died. A leftover setting fails at
  startup and names its replacement.
- **Internal reasoning is required.** Kestrel now does its own thinking on an
  OpenAI-compatible endpoint set in a new `[reasoning]` table, with the key in
  `KESTREL_REASONING_API_KEY`; it does not start without them. Every turn
  without a checked-out repository runs there instead of on an agent backend,
  and each role can use its own endpoint or model. Technical interviewers now
  get a read-only checkout and stay on the agent backend.
  `board_input_security_timeout_seconds` is removed. See
  `docs/configuration.md`.
- **PostgreSQL replaces SQLite.** `KESTREL_DATABASE_URL` is required
  (`postgresql://user:password@host:5432/kestrel`); kestrel does not
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

### Added

- **A light understanding step that keeps the reporter's answers.** The
  restatement is short and non-technical and asks at most three questions;
  "I don't know" is a fine answer. Answering them on the ticket counts as a
  correction, and the revision works from the reply in full, not a summary.
  The confirmed restatement is attached to the ticket as `Understanding.md`,
  and every later step works from it, with the ticket as written kept for
  reference.
- **UI work uses the browser tool.** The coder now follows fixed steps for
  UI changes: start the app, look at it and take the screenshots with the
  browser MCP tool, never with a browser script of its own, and report only
  the tool's exact error if it fails. The verifier opens the app the same
  way, and treats missing screenshots it could have taken as a gap to fix.
- **The merge request follows every later round.** Requested changes, a
  clarification or a CI repair push their commits and add a comment listing
  them with the coder's summary, or saying why nothing needed changing.
  Kestrel keeps a visible "Maintained by kestrel" section of the description
  up to date and leaves the rest as people wrote it.
- **Agent tooling stays out of the merge request.** The coder keeps helper
  scripts and notes in `.kestrel/scratch/`, which is never committed, and
  drives the browser with its tool rather than a script. The verifier reports
  a committed tooling file, and delivery warns about one.
- **Kestrel explains itself in the log.** `kestrel.board.decisions` logs every
  decision and its reason at info: cards claimed and finished, coordinator
  actions, each verification's findings and round, escalations, delivery
  requested or held and by what, screening verdicts and how replies were
  read. A failed agent tool call is a warning with its error.
  `KESTREL_LOG_LEVELS` follows single loggers at debug, where
  `kestrel.reasoning` logs every internal-reasoning prompt and answer;
  `KESTREL_LOG_TEXT_LIMIT` lifts the 500-character cut on agent text; and
  Claude's thinking is logged like opencode's reasoning.
- **Approved tasks become work items in Jira.** When CAB-2 approves a
  breakdown, each task becomes a sub-task of the request, or, with
  `work_items_project` set, an issue in that project linked to the request.
  Prerequisites become "blocks" links, and a comment lists every task with its
  item. Issue and link types are configurable per Jira source.
- **The approved PRD is attached to the ticket** as `PRD.md`, with a short
  comment in place of the full text.
- **Escalations ask someone.** When the verifier stops on a problem it may
  not settle, the reporter is asked, in kestrel and on the ticket, to clarify
  it, accept the work as built, or abandon the request. A clarification that
  only settles the problem starts a fix. One that changes what was approved,
  or that kestrel cannot be sure about, goes back through PRD sign-off and
  CAB-2. A policy risk goes to the change owner instead of the reporter.
- A delivered request can be sent back from its page with **Request changes**.
  The feedback goes to the coder on the same branch, is verified, and updates
  the same merge or pull request.

### Fixed

- The request page shows its history and activity again: an earlier
  cleanup in this release removed the endpoint they load from.
- A failed card can be retried or abandoned from the request page. The page
  told the operator to do this but had no control for it.
- A card no longer fails when its agent backend goes away mid-turn. It goes
  back to `ready` at once and is retried without using up an attempt
  (`board_backend_outage_retries`), and the log says so in one line.
- A dropped opencode event stream reconnects instead of failing a turn
  that finished, and opencode is told to free a directory after its last
  turn, so a long-running server holds less memory.
- A ticket comment no longer says "link below" when kestrel has no public
  address to link to, and kestrel warns at startup when
  `KESTREL_PUBLIC_BASE_URL` is missing.
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

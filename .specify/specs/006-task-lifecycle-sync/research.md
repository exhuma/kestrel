# Phase 0 Research: Task-Source Lifecycle Sync, Time Tracking, and Operator Hooks

No `NEEDS CLARIFICATION` markers remain in the Technical Context (all resolved during
`/speckit.specify` validation and the follow-up `/speckit.clarify` session — see
`spec.md` → Clarifications). This document instead records the concrete technical
decisions made for each area of the design, each grounded in an existing pattern
already present in the codebase, plus the two decisions that depart from a generic
convention on purpose (naive-UTC timestamps, full-environment hook inheritance).

## 1. Where lifecycle dispatch plugs into the run driver

**Decision**: A new `LifecycleTransitioner`, shaped exactly like the existing
`Notifier` protocol (`notify(run) -> None`, synchronous entry point that schedules
async work via `loop.create_task`), added as one more entry in the `CompositeNotifier`
list built in `get_workflow_service()` (`backend/app/services/workflows.py:2321-2325`).

**Rationale**: `WorkflowService._save()` (`workflows.py:654-693`) is already
documented as "the single choke point for every state-transition checkpoint" and
already calls `self.notifier.notify(run)` unconditionally on every save. Reusing
`CompositeNotifier`'s existing per-notifier failure isolation
(`notifications.py:201-213`, each child wrapped in `try/except` + log) means the new
dispatcher gets "one failing component never blocks another" for free instead of
reimplementing it.

**Alternatives considered**: A second, parallel dispatch path invoked directly from
`_save()` (bypassing `CompositeNotifier`) was rejected — it would duplicate the
failure-isolation logic `CompositeNotifier` already provides, for no behavioral
difference.

## 2. Active/wait time accumulation

**Decision**: A 3-state clock on `WorkflowRun` — `clock_state: "active" | "waiting" |
None` plus `clock_since: datetime | None`, and two accumulators `active_seconds` /
`wait_seconds` (both `float`, seconds). One pure function, `_set_clock(run, state,
now)`, stops whichever clock is running (accumulating into the matching total) and
starts the requested one (or none, at a terminal). See `data-model.md` for the exact
call-site list in `workflows.py`.

**Rationale**: The spec (FR-005, clarified) requires both metrics measured
independently, not one derived from the other by subtraction — provisioning/idle time
around the edges of a run is neither "active" nor "wait," so a derived value would
misattribute it. A single "which clock is running" pointer plus two accumulators is
the minimal state that keeps both numbers exact regardless of how many times a run
pauses and resumes across multiple approval gates.

**Alternatives considered**: Storing every individual pause/resume interval (a list of
`(start, end)` tuples) was rejected — kestrel never needs anything but the *totals*
(FR-005/FR-006 only ever reference the accumulated numbers), so per-interval storage
would be unused complexity.

## 3. Per-platform native status handling

**Decision**:
- **GitHub** (`services/github.py`): a new `GitHubClient.add_label`/label-remove pair.
  `start` adds a configurable label (default `kestrel-in-progress`); `done` removes it
  (does **not** force-close the issue — the existing `Closes #n` PR-body mechanism
  already closes it on merge, and closing it earlier at `done` would misrepresent an
  unmerged PR as resolved); `failed`/`escalated`/`rejected` remove the in-progress
  label and add a distinct configurable terminal label.
- **Jira** (`services/jira.py`): a new `JiraClient.transition_issue(key, transition_id)`
  (`POST /rest/api/2/issue/{key}/transitions`, following the existing
  `_request`/`JiraError` pattern already in that file) driven by per-lifecycle-point
  transition-id fields on `TaskSourceConfig`, all optional — an unset id is a no-op,
  not an error, since not every Jira workflow has a distinct transition for every
  terminal.

**Rationale**: Both map onto the platform's actual native primitive (GitHub has no
"status" beyond labels/open-closed; Jira's workflow transitions are the real
mechanism, but instance-specific, hence configurable rather than hardcoded).

**Alternatives considered**: For GitHub, force-closing the issue at `done` was
considered and rejected (see above — timing mismatch with PR merge). For Jira,
attempting to auto-discover transition ids via the `/transitions` list-endpoint at
runtime was considered and rejected as unnecessary complexity for a single-user tool —
the operator can look the id up once (Jira's own UI/API exposes it) and configure it,
consistent with how every other Jira field in `TaskSourceConfig` already works
(`repo_field`, `jql`, etc. are all operator-supplied, not auto-discovered).

## 4. Native-attempt failure vs. platform-unsupported (clarified)

**Decision**: Treated identically — any status/time write that isn't successfully
applied, for any reason (platform has no such field, or the attempt itself failed:
network error, expired credential, rate limit), falls back to the comment footer. No
distinct retry or alerting path.

**Rationale**: Per the `/speckit.clarify` session — the operator-facing outcome is the
same either way (the ticket still gets the information, via the footer), and building
a distinct failure-classification path was explicitly declined in favor of the simpler
uniform fallback.

## 5. Comment-footer fallback

**Decision**: Reuse `TaskSource.post_comment` (no new API surface). A new pure
formatter, `render_footer(event, *, include_status, include_time)`, in the new
`services/lifecycle.py`, included only for whichever field(s) the native attempt
didn't cover — if both status and time were natively applied, no footer comment is
posted at all.

**Rationale**: Avoids duplicate/noisy comments on a platform that natively supports
everything, while still guaranteeing the operator sees the information somewhere on
every platform.

## 6. Hooks folder mechanism

**Decision**: `HookRunner` (new `services/hooks.py`) lists every executable file
directly inside a source's configured `hooks_dir` (filename-sorted), invokes each via
`asyncio.create_subprocess_exec(path, stdin=PIPE, stdout=PIPE, stderr=PIPE)` — no
`env=` override, so the subprocess inherits kestrel's own process environment — writes
the event JSON via `communicate(input=...)`, wrapped in `asyncio.wait_for(..., timeout=
30)` (clarified). Every hook receives every lifecycle event and self-filters on
`event.kind` (clarified — single location, not one script per named event). See
`contracts/hook-wire-format.md` for the exact stdin/stdout schema.

**Rationale**: `asyncio.create_subprocess_exec` is the existing, only pattern kestrel
uses for subprocess invocation (`services/runner.py` for the `claude` CLI,
`services/git.py` for `git`) — no new subprocess library is introduced. Full
environment inheritance is the explicit, binding product decision (spec FR-011): a
hook must be able to call the ticket's platform API using kestrel's own credentials.
Kestrel has **no existing subprocess-timeout precedent** (`runner.py`/`git.py` both
lack one) — the 30s bound (clarified) is new, introduced specifically for this
untrusted-executable boundary where indefinite hangs are a real risk in a way they
aren't for the operator's own `claude`/`git` binaries.

**Alternatives considered**: Writing JSON to stdin was chosen over CLI arguments
(kestrel's `claude` invocation instead reads NDJSON from stdout, not stdin — no
existing "write structured input" precedent in kestrel, so this is new ground, but
consistent with the user's explicit "git-hook style, stdin/stdout" request). Passing a
stripped/sanitized environment was considered and explicitly rejected — see the
Security section below; full inheritance is intentional, not an oversight.

## 7. Failure isolation for hooks

**Decision**: Non-zero exit, timeout (kill + log), or unparseable stdout: log a
warning (with the hook's path, never full stderr content) and move to the next hook.
Never raises across the `LifecycleTransitioner`/`_save()` boundary.

**Rationale**: Modeled on `CompositeNotifier.notify`'s per-notifier isolation
(`notifications.py:207-213`), not on `GitService._git`'s raise-on-nonzero-exit pattern
(`services/git.py:51-55`) — a bad *user-provided* hook must never abort a *system*
run, which is a materially different failure-tolerance requirement than a failed
internal `git` command (which genuinely should surface as an error).

**Constitution-kit tension, noted and resolved**: `module-fastapi`'s error-handling
guidance calls for domain-specific exception classes for errors crossing a layer
boundary, never a swallowed bare `except Exception`. This is a deliberate,
documented exception to that general rule for exactly this one boundary — a hook's
failure must never propagate, by the same logic `CompositeNotifier` already applies
today to notifier failures. Stated here so it doesn't read as an oversight during
review.

## 8. Stderr / diagnostic-output handling (FR-013)

**Decision**: Hook stderr is logged server-side only (kestrel's own structured logs,
truncated), never included verbatim in any ticket-facing comment or status field.

**Rationale**: FR-013 exists because a hook has access to kestrel's credentials
(decision 6) — its own error output could inadvertently contain a fragment of a
credential or other sensitive response data if the hook's own error handling is
sloppy; echoing that into a public-facing ticket comment would be a credential-leak
vector kestrel itself introduced.

## 9. Startup audit logging of hook directories (FR-016, clarified)

**Decision**: At service startup, for each configured `hooks_dir`, log (via kestrel's
existing structured logger, consistent with the `module-logging-structured` v2 pin)
every executable file found, flagging any that are group/world-writable at `WARNING`.

**Rationale**: A lightweight, purely observational nudge — not an access control —
giving the operator a chance to notice an unexpected script without kestrel enforcing
anything or refusing to start. Directly resolves the `/speckit.clarify` decision to
support this rather than leave auditing entirely to the operator's own tooling.

## 10. Data model / migration approach

**Decision**: New nullable/`server_default`-backed columns on `WorkflowRunRow`
(`active_seconds` default `0.0`, `wait_seconds` default `0.0`, `clock_state` nullable,
`clock_since` nullable), added via one new Alembic migration
(`backend/alembic/versions/0012_run_lifecycle_time.py`), no backfill needed (existing
rows simply start at zero/unset).

**Rationale**: Directly follows the existing, most recent precedent in this codebase —
migration `0011_workflow_run_boundary.py` added a nullable `boundary` column to the
same table with an identical no-backfill rationale ("every existing run simply gets
NULL, which verify treats the same as ... today's behaviour, unchanged").

**Constitution-kit tension, noted and resolved**: `module-database-postgresql`'s
model-conventions section recommends `DateTime(timezone=True)` for all new timestamp
columns. Kestrel's constitution explicitly records "timestamps are stored as naive
UTC" as a permitted, recorded deviation from the usual SQLAlchemy pattern (Technology
& Architecture Constraints → Persistence). The new `clock_since` column follows the
**existing, already-ratified local convention** (naive `DateTime`, matching
`SessionRow.created_at` / `WebhookDeliveryRow.created_at` / `IssueDismissalRow.
created_at` / `NotificationRow.created_at`, none timezone-aware) rather than
introducing a one-off tz-aware column that would be inconsistent with every other
timestamp column in this table's own neighborhood.

## 11. Constitution amendment (Principle I)

**Decision**: Amend the "Access model" bullet in Technology & Architecture Constraints
(`.specify/memory/constitution.md`, currently lines 186-200) to record: kestrel now
executes arbitrary operator-provided executables from a configured, per-task-source
`hooks_dir` at defined lifecycle points; those executables inherit kestrel's full
process environment, including every configured credential, by deliberate design;
`hooks_dir` and its contents are therefore a secret-equivalent trust boundary — not
merely "same trust as host access" — with no sandboxing beyond the failure-isolation
already described (decision 7) and the startup audit log (decision 9). MINOR version
bump (1.2.0 → 1.3.0), following the exact precedent and format of the existing
2026-07-21 webhook-HMAC amendment (same file, SYNC IMPACT REPORT header) — expands a
recorded constraint, redefines no principle.

**Rationale**: Principle I requires this be recorded *before* the capability is relied
upon, not after. Treating the amendment as a first-class Phase-0/implementation
deliverable (rather than a follow-up doc task) is what keeps the Constitution Check
gate honest.

## 12. Quartermaster kit alignment

`resolve_kits` was run once during the pre-plan design phase and again for this
concrete planning step (pinned to this repo's `.quartermaster.toml`: `module-logging-
structured`=v2, `module-http-middleware-hardening`=v2, `module-opentelemetry`=v2).
Top-matched kits: `module-fastapi`, `module-database-postgresql`,
`stack-fastapi-vuetify`. Two kit-vs-local-convention tensions were identified and
resolved above (naive-UTC timestamps in §10, hook-failure exception-swallowing in
§7) — both resolved in favor of an existing, already-justified local convention rather
than the kit's generic default, and both are called out explicitly rather than left
looking like unreviewed deviations. `resolve_kits` MUST be called again per concrete
step of `/speckit.tasks`/`/speckit.implement` as they're reached (standing
Quartermaster instruction, not satisfied by these two upfront calls).

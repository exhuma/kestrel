# Phase 0 Research: Fixture Task Source & Rerun

No `NEEDS CLARIFICATION` markers remain in the Technical Context or `spec.md`
(the terminology, gating model, and code-hosting strategy were settled with
the maintainer during the design-plan session that seeded this spec — see
`/home/claude/.claude/plans/as-kestrel-is-still-serialized-otter.md`). This
document records the concrete technical decisions for each area of the
design, each grounded in an existing pattern already present in the
codebase.

## 1. Fixture task storage layout

**Decision**: One file per task under an admin-configured `fixtures_dir`
(new field on `TaskSourceConfig`), named `<slug>.json`. Each file holds
`{"title": str, "body": str, "code_repo": "owner/name", "base_branch":
str | null}`. `FixtureTaskSource` re-reads the file on every `get_task()`
call rather than caching it — this is what makes edit-then-rerun work
without a restart (spec FR-005), and matches the existing "no caching
layer" posture of `GitHubTaskSource`/`JiraTaskSource`, which also hit their
respective APIs fresh on every call.

**Rationale**: JSON (not TOML/YAML) matches every other structured data file
kestrel already reads/writes at runtime (`config.toml.example` is TOML but
is a *config* file loaded once at startup, a different concern) and needs no
new dependency — `json` is stdlib.

**Alternatives considered**: A single multi-task file (e.g. one
`fixtures.json` array) was rejected — it would make "edit one task" a
diff against a shared file (worse for the admin's stated workflow of
"easily modified and cleaned out"), and would need in-file locking
semantics kestrel doesn't otherwise need. One file per task also gives a
free, obvious task identifier: the filename stem.

## 2. `task_ref` / run-`source` naming

**Decision**: Run-source discriminator value `"fixture-issue"` (extends the
existing `WorkflowRun.source` string, matching the `"github-issue"` /
`"jira-issue"` naming convention exactly — see `models_workflow.py:142-146`
and `WorkflowRunRow.source` in `persistence/tables.py`). `task_ref` format:
`"fixture:<slug>"` where `<slug>` is the fixture file's stem (e.g.
`fixtures_dir/retry-checkout-bug.json` → `task_ref = "fixture:retry-checkout-bug"`).

**Rationale**: `task_ref` is the existing source-neutral dedup/dismissal key
(`ingestion.py::has_run`, `dismissal_store.py`) — giving it a distinct,
unambiguous prefix keeps it visually and programmatically distinguishable
from `"owner/name#123"` (GitHub) and `"RFC-123"` (Jira) with zero risk of
collision, at no cost (no new mechanism; the existing string-keyed stores
don't care about format).

**Alternatives considered**: Reusing the bare filename stem as `task_ref`
(no `"fixture:"` prefix) was rejected — a stray fixture file named e.g.
`"RFC-123.json"` could then collide with a real Jira ref in the shared
dismissal store; the prefix makes collision structurally impossible.

## 3. No new database migration

**Decision**: This feature needs **zero** Alembic migrations.

**Rationale**: `WorkflowRunRow.source` (`persistence/tables.py`) is a plain
`Mapped[str]` with no `CHECK`/enum constraint — it already accepts any
string, so persisting `"fixture-issue"` needs no schema change. The new
`rerunnable` field on `WorkflowSummary`/`WorkflowDetail` is computed at
request time from `self._task_source(run).visibility()` (exactly like the
existing `allow_incomplete_answers`, computed from `get_settings()` in
`_detail()`) — it is never stored. `fixtures_dir` lives in the file-only
`task_sources` TOML config, not the database, matching every other
`TaskSourceConfig` field.

**Alternatives considered**: N/A — confirmed by reading
`persistence/tables.py` directly rather than assumed.

## 4. Rerun's visibility guard and its HTTP mapping

**Decision**: A new domain exception, `RerunNotAllowedError`
(`backend/app/services/exceptions.py`, alongside the existing
`WorkflowNotFoundError`/`InvalidWorkflowStateError`), raised by
`WorkflowService.rerun()` when `self._task_source(run).visibility() !=
"private"`. Registered in `main.py` with its own `@app.exception_handler`,
mapped to **403** (Forbidden) — distinct from the existing 409 used for
`InvalidWorkflowStateError` ("wrong phase for reply/approve/reject").

**Rationale**: 403 signals "this action is not permitted for this
resource," which matches the semantics exactly — it is a policy/permission
refusal, not a transient state conflict that might succeed if retried later
(409's connotation). Reusing `InvalidWorkflowStateError` was considered
(it already maps to 409 and needs no new handler) but rejected: its own
docstring scopes it to "reply/approve/reject hits the wrong phase," and a
public-source run is *never* going to become reru-able by reaching a
different phase, so 409's "try again later" implication would be actively
misleading.

**Alternatives considered**: See above (reusing `InvalidWorkflowStateError`
+ 409).

## 5. Code hosting for the fixture source

**Decision**: The fixture `[[task_sources]]` entry reuses
`TaskSourceConfig`'s existing `code_host` / `code_host_base_url` /
`code_host_token_env` fields (today used only by Jira) and gets wired to a
real `GitHubCodeHost`/`GitLabCodeHost` instance in `bootstrap.py`, exactly
like the Jira wiring at `bootstrap.py`'s `jira_sources` block. No new
`CodeHost` implementation is written.

**Rationale**: Maintainer's explicit choice (see design-plan session):
"disposable" is a property of the *ticket*, not the code host — branches
still need a real, reachable git remote to push to and open a real draft
change request against for review, and `GitHubCodeHost`/`GitLabCodeHost`
already do that correctly and are already tested.

**Alternatives considered**: A fully-offline local `CodeHost` (bare repo,
local JSON change-request record) was evaluated during planning and
rejected for v1 in favor of this simpler reuse — see Complexity Tracking in
`plan.md`. It stays available as a later addition if a fully network-free
fixture source becomes a concrete need.

## 6. Poll source pattern

**Decision**: `FixturePollService` implements the existing `PollSource`
Protocol (`backend/app/services/poll_source.py` — `name`,
`list_work_items()`, `run_forever()`) by listing files in `fixtures_dir` and
calling `ingestion.maybe_start_run(source="fixture-issue", task_ref=...,
code_repo=..., base_branch=...)` for each — mirroring
`ReconcileService`/`JiraPollService`'s existing shape exactly. Registered
alongside them in `configured_poll_sources()`.

**Rationale**: `ingestion.maybe_start_run` is already source-neutral
(confirmed by reading `ingestion.py`) — no change needed there. Following
the existing `PollSource` shape means the fixture source participates in
kestrel's normal scheduled-check loop (`python -m app poll` / the app
lifespan) with no special-casing anywhere else in the system.

**Alternatives considered**: See Complexity Tracking in `plan.md` (skipping
polling entirely, requiring manual first-run triggering — rejected).

## 7. Constitution amendment (Principle I)

**Decision**: A new bullet in the "Access model" section of
`.specify/memory/constitution.md`, following the exact style of the existing
webhook-HMAC (1.2.0) and `hooks_dir` (1.3.0) deviation bullets: record that
every `TaskSource` implementation declares a `visibility()` capability
(`"public"` | `"private"`), that GitHub and Jira are `"public"`, and that
kestrel's rerun action — the one operation that discards and replaces a
run's history — is permitted only when `visibility() == "private"`. State
explicitly that the existing delete/cleanup actions were already safe (they
never touch the remote ticket) and this amendment does not change that; it
only formalizes the guarantee and extends it to gate the new action. This
is a MINOR version bump (new permitted-deviation-adjacent constraint added,
no principle redefined), same class of change as the two prior amendments.

**Rationale**: Principle I requires any intentional new binding constraint
be recorded before it is relied upon. Following the two existing precedents
keeps the amendment style consistent and reviewable.

**Alternatives considered**: N/A — the existing amendment format is the only
one this project uses (see Sync Impact Reports for 1.2.0 and 1.3.0 at the
top of `constitution.md`).

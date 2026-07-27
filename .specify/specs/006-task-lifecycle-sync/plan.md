# Implementation Plan: Task-Source Lifecycle Sync, Time Tracking, and Operator Hooks

**Branch**: `006-task-lifecycle-sync` | **Date**: 2026-07-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `.specify/specs/006-task-lifecycle-sync/spec.md`

## Summary

Kestrel's `TaskSource` port currently only reads tickets and posts fixed-template
comments (`ports.py:82-104`). This feature adds a `transition()` protocol method so
GitHub and Jira sources push "in progress" / "done" / failure-terminal status back to
the ticket (natively where the platform supports it — GitHub via labels, Jira via
configurable workflow-transition ids — else via a comment-footer fallback); a 3-state
active/wait clock on `WorkflowRun`, persisted via a new Alembic migration, reporting
active time to a native field when configured and both metrics via the footer
otherwise; and a per-task-source `hooks_dir` mechanism (`HookRunner`) that invokes
operator-provided executables at every lifecycle event with JSON on stdin, inheriting
kestrel's full process environment by design so a hook can call the ticket's API with
kestrel's own credentials. All three pieces are wired into the existing
`WorkflowService._save()` choke point via a new `Notifier`-shaped
`LifecycleTransitioner`, added to the existing `CompositeNotifier` fan-out
(`workflows.py:2321-2325`) — additive to, never a replacement for, kestrel's own
behavior. Backend-only: per the clarified spec scope, no frontend/UI work is included.

## Technical Context

**Language/Version**: Python 3.12+ (`backend/pyproject.toml:7`)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x, Alembic ≥1.13, pydantic-settings
≥2.14 — all already in use; no new dependency is required for this feature (subprocess
invocation uses `asyncio`, stdlib-only, matching the existing pattern in
`services/runner.py` and `services/git.py`).

**Storage**: SQLite via SQLAlchemy 2.x, schema owned by Alembic (`backend/alembic/`) —
unchanged; this feature adds columns to the existing `workflow_run` table via one new
migration.

**Testing**: pytest (backend). Per Constitution Principle III, tests MUST NOT shell out
to a real subprocess for hook scripts — `asyncio.create_subprocess_exec` is mocked, the
same convention already required for the `claude` CLI boundary.

**Target Platform**: Linux server / Docker (bundled image) and run-from-source dev flow
— both existing run modes, unaffected by this feature.

**Project Type**: Web service (FastAPI backend + Vue/Vuetify frontend) — this feature
is **backend-only**; the spec's clarification session explicitly scoped out any
in-app UI surfacing of the new metrics/status.

**Performance Goals**: N/A beyond the spec's own constraint — a hook script invocation
is bounded at 30s (FR-010, clarified); no throughput target (single-user tool).

**Constraints**: Timestamps stored as naive UTC (constitution, Technology &
Architecture Constraints — a recorded, permitted deviation from the generic
`module-database-postgresql` kit's tz-aware-`DateTime` recommendation; the new clock
columns follow the existing repo-wide naive-UTC convention, not the kit's generic
default). Hook subprocesses inherit kestrel's full process environment by deliberate
design (FR-011) — this is the feature's central security-posture decision and requires
a constitution amendment before it is relied upon (Principle I).

**Scale/Scope**: Single concurrent user (constitution Principle IV); a handful of
configured task sources, each with at most a handful of hook scripts — no scale
engineering needed.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment |
|---|---|
| I. Contract Fidelity | **Requires a recorded amendment before implementation lands.** Hook subprocesses inheriting kestrel's full environment (thus every configured credential) is an intentional departure from "no new capability silently changes the trust model" — Principle I requires it be recorded in the constitution, with rationale, before it is relied upon. This is a known, planned amendment (see `research.md` → "Constitution amendment"), not a violation to avoid; it is the reason this plan treats the amendment as a Phase 0 deliverable rather than an afterthought. |
| II. Layered, Backend-Owned Architecture | Pass. All new logic lives in `backend/app/services/` (routers unaffected — no new HTTP endpoints); schema changes go through Alembic only (no `create_all`, no raw DDL). |
| III. Test-First Discipline | Pass, with an explicit convention note: `HookRunner` tests mock `asyncio.create_subprocess_exec` (never spawn a real executable), matching the existing required treatment of the `claude` CLI subprocess boundary. |
| IV. Deliberate Simplicity & Single-User Scope | Added complexity is real (new protocol method, new config surface, new subprocess-execution path, dual-clock state machine) — see Complexity Tracking below for the required justification. No speculative generality: hooks are scoped to lifecycle events only, config fields are all optional with safe no-op defaults, and no sandboxing/plugin-discovery machinery beyond "list an executable directory" is introduced. |
| V. Kit-Aligned Consistency & Observability | Pass. `resolve_kits` was called for this planning step (pins: `module-logging-structured`=v2, `module-http-middleware-hardening`=v2, `module-opentelemetry`=v2, matching `.quartermaster.toml`). Hook-invocation logging and the new startup audit log (FR-016) use kestrel's existing structured-logging setup, consistent with the v2 (OpenTelemetry-based) pin — no ad hoc `print`/plain-text logging introduced. No frontend/UI work in this feature, so `module-vue-*` kits are not applicable here. |

**Gate result**: PASS, conditional on the Principle I constitution amendment being
authored as part of this feature's Phase 0/implementation (tracked explicitly below,
not deferred).

## Project Structure

### Documentation (this feature)

```text
.specify/specs/006-task-lifecycle-sync/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output
│   ├── task-source-protocol.md
│   └── hook-wire-format.md
└── tasks.md              # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── ports.py                       # + LifecycleEvent, TaskSource.transition()/supports_time_spent()
│   ├── models_workflow.py             # + WorkflowRun.active_seconds/wait_seconds/clock_state/clock_since
│   ├── config_models.py               # + TaskSourceConfig lifecycle/hooks fields
│   ├── notifications.py               # unchanged; LifecycleTransitioner composes alongside it
│   ├── services/
│   │   ├── workflows.py               # _set_clock call sites; terminal-stop in _save(); wiring in get_workflow_service()
│   │   ├── time_tracking.py           # NEW — _set_clock
│   │   ├── lifecycle.py               # NEW — LifecycleTransitioner, render_footer
│   │   ├── hooks.py                   # NEW — HookRunner, startup audit logging
│   │   ├── github.py                  # + GitHubClient.add_label, GitHubTaskSource.transition()
│   │   └── jira.py                    # + JiraClient.transition_issue/set_field, JiraTaskSource.transition()
│   └── persistence/
│       ├── tables.py                  # + WorkflowRunRow columns
│       └── workflow_store.py          # + column mapping in save()
├── alembic/versions/
│   └── 0012_run_lifecycle_time.py     # NEW migration
└── tests/
    ├── test_lifecycle_transitioner.py # NEW
    ├── test_hooks.py                  # NEW
    ├── test_active_time.py            # NEW
    ├── test_github_ports.py           # extended
    └── test_jira_ports.py             # extended (or new, if not already present)

config.toml.example                    # document new TaskSourceConfig fields
docs/hooks.md                          # NEW — operator security warning + wire format
.specify/memory/constitution.md        # Access-model amendment (Principle I)
```

**Structure Decision**: Existing FastAPI backend layering (`routers → services →
persistence`) is unchanged; this feature adds two new service modules
(`time_tracking.py`, `lifecycle.py`, `hooks.py`) rather than growing
`workflows.py` further (that file is already large — new logic goes in its own
module and is *called from* `workflows.py`, keeping `workflows.py`'s own diff to
call-site wiring only). No frontend changes (`frontend/` is untouched by this
feature per the clarified spec scope).

## Complexity Tracking

> Required by Principle IV governance: complexity that could look unjustified must be
> justified here, with the simpler alternative considered and why it was rejected.

| Added complexity | Why needed | Simpler alternative rejected because |
|---|---|---|
| Hook subprocess mechanism (`HookRunner`, arbitrary executable invocation, full env inheritance) | Jira instances are configured with workflow transitions/custom fields kestrel cannot enumerate in advance (spec User Story 3); without an escape hatch, those operators get no lifecycle sync at all beyond the generic footer. | A fixed, hardcoded set of "extra" Jira actions was rejected — it cannot anticipate every instance's configuration, and would need a kestrel code change (violating SC-004: no code change required to add a custom action) every time an operator's Jira setup differs from the ones already coded for. |
| Dual clock (`active_seconds` **and** `wait_seconds`, not one derived from the other) | The spec (clarified, User Story 2 / FR-005) explicitly requires both measured independently — "true implementation effort" must exclude gate-wait time, and gate-wait time itself is a first-class metric the user asked to see, not a byproduct. | Deriving `wait_seconds = total_elapsed - active_seconds` was rejected — terminal/idle time before the run starts or after it stops is neither active nor wait, so a subtraction would silently misattribute that slice as one or the other; two explicit accumulators avoid that ambiguity entirely. |
| New `TaskSource.transition()` protocol method + per-platform native handling (GitHub labels, Jira transition ids) | The spec's User Story 1 requires the ticket to reflect real status without the operator opening kestrel; a footer-only approach (skipping native transitions) was considered but rejected because it produces a strictly worse result on platforms that *do* support native status (the ticket's own status field/board view stays stale even though a comment mentions the true state). | Native handling only where cheap: GitHub gets label add/remove (already have a client), Jira gets a configurable transition-id lookup (no assumed workflow shape) — no attempt to build a general-purpose "field mapper" beyond these two concrete, spec-scoped needs. |

## Phase 0 & Phase 1 outputs

See `research.md`, `data-model.md`, `contracts/*.md`, and `quickstart.md` in this
directory.

## Post-Design Constitution Check (re-evaluated after Phase 1)

Re-reading the Constitution Check table above against the completed `data-model.md`
and `contracts/*.md`: no new violations were introduced by the detailed design beyond
the one already flagged (Principle I amendment for hook env-inheritance). The
Complexity Tracking table above still fully accounts for every new module/mechanism
named in Project Structure — no additional unjustified complexity was found during
Phase 1 design work. **Gate result: PASS**, same condition as before (constitution
amendment must land alongside implementation, not be deferred past it).

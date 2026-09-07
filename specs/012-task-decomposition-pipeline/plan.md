# Implementation Plan: Task Decomposition Pipeline

**Branch**: `012-task-decomposition-pipeline` | **Date**: 2026-09-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/012-task-decomposition-pipeline/spec.md`

## Summary

Insert two new steps ahead of today's `refine → design → code → verify →
deliver` pipeline (`docs/architecture.md`;
`backend/app/services/workflows/driver/__init__.py`): a new `describe` step
(understanding-checkpoint — kestrel restates the task, the requester
confirms or amends, gated like today's PRD approval) and a new
`gap_analysis` step (technical analysis, entered only once the now
altitude-restricted `refine`/PRD-approval gate is passed — see below).
`gap_analysis` is gateless and **run-terminating on success**: it produces
a technical-analysis document plus one or more independent, self-contained
follow-up tasks published back to the originating ticket's task source,
sets a new terminal run status (`decomposed`), and ends the run without
ever reaching `design`/`code`/`verify` for the original ticket
(confirmed run-shape decision 1/3, `spec.md`). A follow-up task, once
independently and later triggered the same way any task is triggered
today, is recognized via an extension of the existing "already-refined"
sentinel mechanism (`backend/app/services/workflow_text.py`) and skips
straight to `design` (confirmed decision 2/3).

Both new step names (`describe`, `gap_analysis`) are not invented — they
reuse two fully-configured-but-never-wired entries already sitting in
`backend/app/policy.py`'s `DEFAULT_MODELS`/`STEP_REQUIREMENTS` maps
(`research.md` R1), which is the strongest available signal for what this
pipeline was always meant to look like. `refine`'s existing
coordinator/profile-selection (`backend/app/profiles.py`,
`backend/app/services/workflows/interview/`) is restricted, when reached
through this pipeline, to non-technical/requestor-altitude profiles only;
`gap_analysis` reuses the identical fan-out → reconcile → critic shape
already proven by the refine interview, but analysis-flavored and run
against the technical-altitude profiles instead (`research.md` R7/R8).
This applies uniformly to every ingested task, regardless of source or
size (confirmed decision 3/3) — there is no branch between an "old" and a
"new" pipeline shape.

**Binding constraints** (from `.specify/memory/constitution.md` v1.4.0):
all new logic stays in backend services (routers → services → stores,
Principle II); behaviour ships with pytest that mocks the agent backends
and every `TaskSource`/`CodeHost` (Principle III, no real `claude`
subprocess, no real GitHub/Jira, no production DB); no multi-user auth
implication (Principle IV); kits resolved per task (Principle V). No new
runtime dependency and no new database migration are required (`research.md`
R10) — a materially simpler footprint than feature 003's Jira-ingestion
plan, since this feature only reshapes an already-existing pipeline rather
than adding a new source.

## Technical Context

**Language/Version**: Python 3.12 (backend, `uv`), TypeScript 5 / Vue 3
(frontend, `npm`) — unchanged from the existing stack.

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x, Alembic, pydantic-settings
(existing). No new runtime dependency — this feature reshapes the existing
workflow driver/interview/prompts modules and extends the existing
`TaskSource` protocol; it adds no new I/O client.

**Storage**: SQLite via SQLAlchemy 2.x, schema owned by Alembic. **No new
migration** (`research.md` R10, `data-model.md`): `WorkflowStepRow` is
already keyed by `(workflow_id, position)` with a free-form `name`, so
extending `Step.sequence()` from four to six entries needs no schema
change; `WorkflowRunRow.status` is already an unconstrained string column,
so the new `"decomposed"` terminal value and the new `awaiting_*`/
`describing`/`analyzing` transient values need none either.

**Testing**: pytest with every `TaskSource`/`CodeHost` and agent-backend
call mocked/stubbed (Constitution III) — no real `claude` subprocess, no
real GitHub/Jira/fixture I/O beyond the existing fixture-file test
convention, no production database. New coverage mirrors the existing
`backend/tests/test_workflow_gate.py`, `test_workflow_interview.py`,
`test_prd_delivery.py`, `test_autonomous_no_gate.py` shape, extended for
the `describe` gate and the `gap_analysis` step's self-containment check
and `create_subtask` contract. vitest for the frontend's new gate-approval
screen and updated status/step label maps.

**Target Platform**: single-user Linux service, API loopback-bound and
unauthenticated (or OIDC-gated per feature 011) — unchanged. No new
endpoint: the new `describe` gate reuses the existing generic `/approve`/
`/reject` router endpoints unmodified (`gate.py::resolve()`'s
`run.status.endswith("_approval")` check already accepts the new status
with zero code change — `research.md`/`data-model.md`).

**Project Type**: web application (FastAPI backend in `backend/`, Vue SPA
in `frontend/`) — unchanged.

**Performance Goals**: not latency-sensitive, matching every existing
gateless step; `gap_analysis`'s fan-out/reconcile/critic round is bounded
the same way `refine`'s interview rounds already are (no new unbounded
loop introduced).

**Constraints**: two human gates in sequence before any technical work
(`describe`, then the now-altitude-scoped `refine`) instead of today's one;
`gap_analysis` gateless (matches `design`'s existing autonomy — no third
gate added, per `spec.md` Assumptions); every follow-up task published by
`gap_analysis` must be self-contained (spec.md FR-010, enforced by a
completeness self-review turn before publishing, `research.md` R8);
creating a follow-up task must never itself start a new run (spec.md
FR-013, enforced per-source at the trigger-condition level, `research.md`
R4) — no mechanism exists to enforce this centrally, since the three
sources' triggers (GitHub label, GitHub/Jira poll re-list, Jira JQL) share
no common code path today.

**Scale/Scope**: unchanged from the existing pipeline — single maintainer,
a handful of concurrent runs. `gap_analysis` may fan out to up to the full
technical-profile roster (`developer`, `infosec`, `dba`, `architect`,
`ops`, `qa`) per run, the same order of magnitude `refine`'s interview
already fans out to.

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.4.0.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Contract Fidelity | ✅ **No new deviation** | No off-loopback endpoint added; the new `describe` gate reuses the existing generic approval endpoints unchanged. `frontend/src/types/` gains no new business type (status/step-name string enums only, mirroring how feature 003 added `designing`/`coding`/`verifying`/`escalated`) — both sides updated together so the type contract stays in sync. |
| II. Layered, Backend-Owned Architecture | ✅ | All new logic (`describe()`/`gap_analysis()` driver functions, altitude-restricted roster views, `create_subtask` per-source implementations, the sentinel extension) lives in backend services behind routers; the frontend only renders new status/step labels and a new gate-approval screen, reusing the existing approve/reject/amend UI pattern. No schema change, so no `create_all`/raw DDL question arises. |
| III. Test-First Discipline | ✅ | Each new/changed unit ships with tests: the `describe` gate (approve / reject-with-feedback / reject-without-feedback, mirroring existing `refine` gate tests), altitude-restricted roster selection, `gap_analysis`'s self-containment check (task that fails then passes on revision), the extended sentinel fast path, and `create_subtask` per source (GitHub: no trigger label; Jira: native sub-task + parent link; fixture: parent-linked file) — all against mocked `TaskSource`/agent backends, no real `claude`/GitHub/Jira/production DB. |
| IV. Deliberate Simplicity & Single-User Scope | ⚠️ **Justified complexity** | Additions are recorded in Complexity Tracking below (two new steps/gate, one new required port method, one new sentinel, one new terminal status) — each need-driven by the requester's explicit three-part ask, none speculative. Notably **smaller** in footprint than a typical feature here: no new dependency, no new database migration, no new WorkflowRun/WorkflowStep field (`research.md` R10) — the design deliberately reuses existing gate/interview/sentinel/artifact machinery rather than building parallel mechanisms. |
| V. Kit-Aligned Consistency & Observability | ✅ | Kits resolved per task (`resolve_kits` called before this planning phase). No hard-coded UI colours — the new gate-approval screen and status/step labels reuse existing Vuetify theme tokens (`WorkflowPanel.vue`'s existing badge/status pattern). Structured logging: `gap_analysis` publishing outcomes (per-follow-up-task created / self-containment-revised / failed) logged the same way `ingestion.py` already logs `ingest outcome=...`. |

**Gate result**: PASS. No constitution amendment is required — this feature
introduces no new off-loopback surface, no new credential, and no new
trust boundary; it reshapes an in-process pipeline using only mechanisms
(gates, sentinels, artifact handover, per-source `TaskSource` adapters)
the constitution and existing amendments already cover.

## Project Structure

### Documentation (this feature)

```text
specs/012-task-decomposition-pipeline/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   ├── workflow-states.md
│   ├── task-source-subtask-port.md
│   └── gap-analysis-output.md
├── checklists/
│   └── requirements.md
└── tasks.md              # /speckit-tasks output (not created here)
```

### Source code (repository root) — files touched / added

```text
backend/app/
├── models_workflow.py                # EXTEND — Step gains DESCRIBE, GAP_ANALYSIS
├── ports.py                          # EXTEND — TaskSource.create_subtask
├── policy.py                         # UNCHANGED — describe/gap_analysis entries already present
├── profiles.py                       # EXTEND — altitude-scoped roster views (research.md R7)
├── services/
│   ├── workflow_text.py              # EXTEND — SUBTASK_SENTINEL + helpers
│   ├── github.py                     # EXTEND — GitHubClient.create_issue; GitHubTaskSource.create_subtask
│   ├── jira.py                       # EXTEND — JiraClient sub-task create; JiraTaskSource.create_subtask
│   ├── fixture.py                    # EXTEND — FixtureTaskSource.create_subtask
│   ├── ingestion.py                  # UNCHANGED — no code path change (research.md R4)
│   └── workflows/
│       ├── driver/__init__.py        # EXTEND — describe(), gap_analysis(); continue_run() re-sequenced;
│       │                             #          drive() gains the SUBTASK_SENTINEL fast-path branch;
│       │                             #          design() reads run.steps[1] instead of run.steps[0]
│       ├── gate.py                   # UNCHANGED — resolve()/await_gate() already generic
│       ├── interview/                # EXTEND — reused fan-out/reconcile/critic shape for gap_analysis
│       ├── artifacts.py              # UNCHANGED — write_artifact()/artifact_slot() reused for technical-analysis.md
│       ├── prompts.py                # EXTEND — DESCRIBE_PROMPT, altitude-scoped COORDINATOR_PROMPT variant,
│       │                             #          GAP_ANALYSIS prompts (generation/reconcile/self-containment critic)
│       └── shared.py                 # EXTEND — _TRANSIENT gains "describing", "analyzing"
├── persistence/tables.py             # UNCHANGED — no schema change (research.md R10)
└── routers/workflows.py              # UNCHANGED — existing approve/reject/answers endpoints already generic

frontend/src/
└── components/WorkflowPanel.vue      # EXTEND — new gate-approval UI for `describe`; status/step label maps
                                       #          gain describing/analyzing/decomposed and awaiting_describe_approval
                                       #          (already large at 723 lines — watch `task quality` file-size
                                       #          limits during implementation; split into a sub-component if hit)

backend/tests/…, frontend/tests/…     # NEW tests per Constitution III (see Testing above)
docs/architecture.md, docs/*          # UPDATE — pipeline narrative ("Design trade-offs" section),
                                       #          workflow-states contract cross-reference
```

**Structure Decision**: The existing `backend/` + `frontend/` split and the
routers → services → stores layering are unchanged. This feature is
additive-in-place: it extends the existing driver/interview/prompts/ports
modules rather than introducing new top-level services, since (unlike
feature 003's new Jira source) there is no new external system to
integrate — only new phases in an already-existing pipeline and one new
capability on an already-existing port.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| **Two new pipeline steps + one new human gate** (`describe`, `gap_analysis`) | The requester explicitly asked for an understanding-checkpoint before any interview, and a technical-analysis phase after PRD approval, each structurally distinct from what `refine`/`design` already do | Folding the checkpoint into `refine` as a "round zero" was considered and rejected (`research.md` R1): a restate-and-confirm round has no questions, a materially different shape from `refine`'s question-asking loop, and conflating them would make `refine`'s gate ambiguous about what it's approving |
| **New required `TaskSource.create_subtask` method** (`ports.py`; three implementations) | Decomposition must publish follow-up tasks back to the ticket's own tracker (spec.md FR-011), and this applies uniformly to every source (spec.md FR-016) — there is no source that can skip it | A shared/generic "create linked ticket" helper across `attach`/`post_comment` was considered and rejected (`research.md` R3): GitHub, Jira, and fixture model "this is a subdivision" too differently for one generic call to avoid leaking provider detail |
| **New sentinel (`SUBTASK_SENTINEL`)** (`workflow_text.py`) | A promoted follow-up task must skip three already-answered phases (spec.md FR-015) without any ingestion caller needing to know a ticket is a follow-up *before* fetching its body | A new `WorkflowService.create(start_step=...)` parameter was considered and rejected (`research.md` R5): it would need every ingestion caller (webhook, reconcile, Jira poll, fixture poll) updated to detect "this is a follow-up" pre-fetch, which none of them can do today; the sentinel needs no caller change at all |

**Not added** (YAGNI):
- **No new "pending promotion" suppression store.** The requester's own
  example for triggering a follow-up task later ("a human applies the
  trigger label to it") is exactly today's existing ingestion gesture; a
  second, parallel promotion mechanism was considered and rejected
  (`research.md` R4) as speculative generality duplicating a control the
  label/JQL gate already provides.
- **No third (technical-analysis) approval gate.** Not requested; kept
  gateless to match `design`'s existing autonomy (`spec.md` Assumptions).
- **No new database column or migration.** The follow-up task list
  `gap_analysis` produces is never re-read by kestrel after publishing (the
  parent run ends immediately) — it is fully recorded in the published
  technical-analysis document and each follow-up ticket's own body, not in
  kestrel's own state (`research.md` R10).
- **No new `Profile.altitude` field on the roster.** A filtered
  `roster_summary()` view achieves the same restriction at the call site;
  left as an implementation-phase choice between the two functionally
  equivalent options (`research.md` R7), not frozen here.

# Implementation Plan: Behavioral Verify Evidence

**Branch**: `feat/005-behavioral-verify-step` | **Date**: 2026-07-24 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `.specify/specs/005-behavioral-verify-step/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

The `verify` step's adjudication currently rests on a diff read plus
operator-configured shell checks. This feature grounds it in the *observed
behavior* of the running, modified project: the `design` step classifies the
project's user-facing boundary (HTTP API / web UI / both / none); when a
boundary exists, `verify` gains a tool-enabled "explore" turn that launches
and exercises the app for real, using whatever tools (Bash, MCP — Playwright
or otherwise) the operator's own backend already provides; a second,
resumed "verdict" turn (back in `plan` mode) extracts a reliable
accept/reject decision the same way it does today, now carrying
self-reported observations that merge into the same `Evidence` list
`CheckRunner` already populates — so the existing failing-observation
invariant applies uniformly. Requirement conformance (behavioral +
deterministic evidence) is the only thing that can force a reject;
code-quality/documentation observations become advisory feedback. Each run
gets a committed, human-readable `verify-report.md` audit trail that is
never re-checked by any later run. The coder's prompt gains an explicit
TDD/testing-pyramid instruction so durable regression coverage stays the
coder's job. No new dependencies.

## Technical Context

**Language/Version**: Python 3.11+ (backend, `uv`-managed); TypeScript/Vue 3
(frontend — not touched by this feature beyond doc updates).

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x + Alembic, `httpx` — all
already present, unchanged. **No new dependency is introduced** (Playwright
or any HTTP-testing library is deliberately *not* added; verify delegates to
whatever tools the operator's own `claude`/opencode backend already has).

**Storage**: SQLite via SQLAlchemy/Alembic, as today. One new nullable
column (`WorkflowRunRow.boundary`) via a new Alembic migration.

**Testing**: pytest (backend, mocked backend/session per Constitution
Principle III — no real `claude` subprocess or real app process in tests);
vitest (frontend; only touched if a future increment adds UI surface, out of
scope here).

**Target Platform**: Linux server (Docker image) and run-from-source dev
flow — both must keep working, unchanged.

**Project Type**: Web service (FastAPI backend + Vue/Vuetify frontend,
existing monorepo layout). This feature is backend-only.

**Performance Goals**: N/A beyond what already governs every step's turn
(existing per-backend timeout mechanism; no new timeout/budget introduced —
see `research.md` R1/R2).

**Constraints**: Constitution Principle IV (no unjustified new
dependency) — satisfied by design (R1 in `research.md`). Constitution
Principle III (test-first, no real subprocess in tests). Must not regress
existing verify-loop tests' behavior for the `boundary="none"`/no-checks
paths (backward compatible default).

**Scale/Scope**: Single operator, one run's worktree at a time per repo
(existing per-mirror lock) — no new concurrency concerns.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Contract Fidelity** — PASS. No frontend/backend type-contract change:
  `boundary` and the extended verdict `observations` stay backend-internal
  in this feature (see Assumptions in spec.md); no `frontend/src/types/`
  mirror is required because nothing new crosses the API boundary yet.
- **II. Layered, Backend-Owned Architecture** — PASS. All new logic lives in
  `backend/app/services/workflows.py` (orchestration),
  `backend/app/services/workflow_text.py` (parsing), and
  `backend/app/persistence/`/`backend/alembic/` (schema, via a proper
  migration — no `create_all()`/raw DDL). Nothing added to the frontend.
- **III. Test-First Discipline** — PASS, and directly reinforced: FR-010
  requires the *coder's* prompt to demand TDD, and this feature's own
  backend changes ship with pytest coverage per `contracts/verify-evidence-v2.md`'s
  test contract, using mocked backends/sessions exactly like existing
  `test_verify_loop.py` coverage.
- **IV. Deliberate Simplicity & Single-User Scope** — PASS. Zero new
  dependencies (the central design choice, R1 in `research.md`); no new
  config surface either — `boundary` is inferred, not operator-configured.
  Complexity Tracking table below is empty — no violation to justify.
- **V. Kit-Aligned Consistency & Observability** — PASS. Reuses existing
  idioms throughout (delimiter-tag parsing, `_write_artifact`, write-through
  persistence) rather than introducing new ones; no new UI styling.

No gate violations. Complexity Tracking table intentionally empty.

*Post-Phase-1 re-check*: unchanged — the Phase 1 design (data-model.md,
contracts/verify-evidence-v2.md, quickstart.md) introduces no dependency,
no new config, and no schema mechanism beyond one additive nullable column
via Alembic. All gates still PASS.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/005-behavioral-verify-step/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/
│   └── verify-evidence-v2.md
└── tasks.md              # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

Existing web application layout (`backend/` FastAPI + `frontend/` Vue) is
unchanged; this feature is backend-only.

```text
backend/
├── app/
│   ├── services/
│   │   ├── workflows.py       # DESIGN_PROMPT/_design(), VERIFY_PROMPT/
│   │   │                      # _code_and_verify() (explore+verdict turns,
│   │   │                      # boundary interpolation), CODE_PROMPT (TDD)
│   │   ├── workflow_text.py   # + extract_boundary()
│   │   └── checks.py          # unchanged (CheckRunner stays as-is)
│   ├── ports.py                # unchanged (Observation/Evidence shapes reused)
│   ├── models_workflow.py      # + WorkflowRun.boundary
│   └── persistence/
│       └── tables.py           # + WorkflowRunRow.boundary column
├── alembic/versions/
│   └── 0011_workflow_run_boundary.py   # new migration (down_revision "0010"
│                                       # — feat/config-toml-and-workflow-ux
│                                       # merged to master first, adding 0009
│                                       # and 0010 ahead of this one)
└── tests/
    ├── test_verify_loop.py         # extended: boundary-driven explore turn,
    │                               # self-reported observations, hard/soft
    │                               # split, verify-report.md contents
    ├── test_workflow_text.py       # extended: extract_boundary coverage
    ├── test_workflow_service.py    # extended: _design() sets run.boundary
    ├── test_workflow_persistence.py # extended: boundary round-trips
    ├── test_workflow_reshape.py    # unchanged expectations verified (still
    │                               # exactly 4 steps, same status sequence)
    └── test_workflow_recovery.py   # unchanged expectations verified on
                                     # resume through a verify round

docs/
├── architecture.md    # note the explore-turn tool-trust model
└── configuration.md   # no new config keys (boundary is inferred, not
                        # configured) — note that explicitly to prevent a
                        # future reader assuming otherwise
```

**Structure Decision**: No new top-level directories or projects. All
changes land inside the existing `backend/app/services/workflows.py` +
`workflow_text.py` + `models_workflow.py`/`persistence/tables.py` +
`alembic/` set, following the file-organization pattern already established
by the 003 feature's verify-evidence work. `frontend/` is untouched (per the
spec's Assumptions — no new UI surface in this feature).

## Complexity Tracking

No Constitution Check violations — this table is intentionally empty.

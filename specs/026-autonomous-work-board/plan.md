# Implementation Plan: Autonomous Work Board

**Branch**: `026-autonomous-work-board` | **Date**: 2026-09-24 | **Spec**:
[spec.md](spec.md)

**Input**: Feature specification from
`/specs/026-autonomous-work-board/spec.md`

## Summary

Replace Kestrel's fixed workflow driver with an event-driven, durable board.
The board stores typed work cards, dependencies, specialist attempts, leases,
immutable handoff artifacts, gates, security reviews, and external projections.
An event-driven coordinator proposes bounded actions; deterministic backend
policy validates every action before state changes. Configured specialists claim
eligible cards independently, with parallel read-only work and one write lease
per repository. Task sources retain their request and human-feedback roles but
receive only selected milestones.

## Technical Context

**Language/Version**: Python 3.12 backend; TypeScript 6 / Vue 3.5 frontend

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, Pydantic,
Vue 3, Vuetify 4; add `@vue-flow/core` for the read-only graph

**Storage**: SQLite for board metadata and durable filesystem content storage
for artifact/input bodies; project-material artifacts stay in the worktree

**Testing**: pytest backend; Vitest and Vue Test Utils frontend; `task quality`

**Target Platform**: Single-user Linux-hosted service, Docker image and
run-from-source developer flow

**Project Type**: FastAPI web service plus Vue/Vuetify single-page application

**Performance Goals**: Board changes publish a current workflow snapshot to a
connected operator within one second under normal local operation; a workflow
with 100 cards remains usable in Board and List views

**Constraints**: Backend owns all policy; Alembic owns schema; SQLite
transactions provide durable claims; public task-source history is forward-only;
untrusted input fails closed; one repository writer at a time; no raw suspect
content in logs, notifications, source replies, or live board payloads

**Scale/Scope**: One operator, several configured sources/backends, dozens of
active workflows, and card graphs of at least 100 cards; clean green-field
replacement with no legacy workflow-state migration

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Design Gate

- **I. Contract Fidelity: Pass.** Replace the workflow API and matching
  frontend types together. Board DTOs are in `contracts/board-api.md`.
- **II. Layered, Backend-Owned Architecture: Pass.** Routers call a board
  application service. Vue renders state and sends intents only.
- **III. Test-First Discipline: Pass.** Build pure policy and transition tests
  before dispatch. Cover input transports, projections, recovery, and mocked
  frontend HTTP.
- **IV. Deliberate Simplicity & Single-User Scope: Pass.** File-backed named
  roles and one scheduler meet the need. Do not add plugins, multi-user auth,
  workflow DSLs, or bidirectional tracker sync.
- **V. Kit-Aligned Consistency & Observability: Pass.** Preserve structured
  logs, health, SSE, and theme tokens. Log opaque identifiers and
  classifications only.
- **Access Model: Pass.** Preserve loopback service and GitHub HMAC ingress.
  Treat source authenticity separately from input safety.
- **Public Source Ownership: Pass.** Source writes go through the durable
  projection ledger; cleanup remains limited to Kestrel-owned records.

### Post-Design Gate

The design retains all pre-design decisions. It creates no new service boundary
requiring a constitutional amendment: specialist prompts are operator-owned
configuration, not executable hooks; all agent dispatch continues through the
existing backend abstraction. The only new frontend dependency is Vue Flow,
justified by the requirement to inspect a changing dependency graph. The board
and list remain complete without its canvas.

## Project Structure

### Documentation (this feature)

```text
specs/026-autonomous-work-board/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output; not created during planning
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/             # Board schema and clean-break removal
├── app/
│   ├── backends/                 # Existing agent adapter protocol
│   ├── persistence/              # Board-focused stores and ORM tables
│   ├── routers/workflows.py      # Board REST and SSE contract
│   ├── services/
│   │   ├── board/                # Policy, coordinator, claims, dispatch,
│   │   │                          # artifacts, quarantine, projections
│   │   ├── feedback/             # Input transport callers, not fixed rewinds
│   │   └── ingestion.py          # Source task -> protected board intake
│   └── storage/workflow_bus.py   # Snapshot ticks for board changes
└── tests/
    ├── test_board_*.py
    ├── test_input_security_*.py
    └── test_workflows_router.py

frontend/
├── src/
│   ├── components/               # Board, list, graph, card detail, dialogs
│   ├── composables/useWorkflows.ts
│   ├── lib/boardGraph.ts         # Pure card/relation -> graph projection
│   └── types/workflows.ts        # Mirrored board business contract
└── tests/
    ├── components/
    └── lib/
```

**Structure Decision**: Keep the existing FastAPI + Vue/Vuetify split. Introduce
a bounded backend `services/board/` package rather than extending the existing
fixed driver or creating a generic engine. Keep tool/runtime wiring in routers,
bootstrap, and adapters; keep board business rules in pure policy and service
modules. Replace the current fixed-step frontend contract as a clean break.

## Complexity Tracking

No constitutional violations require justification.

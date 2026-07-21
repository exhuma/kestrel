<!--
SYNC IMPACT REPORT
==================
Amendment 2026-07-21 (1.0.1 → 1.1.0, MINOR): Fold the standalone repo-level
`contract.md` into this constitution and delete that file. Principle I (Contract
Fidelity) is reworded so THIS document — not an external file — is the
authoritative record of the constraints an agent must honour; the type-contract
rule is retained, and the contract's access model (single-user, unauthenticated,
loopback-bound; shared-secret gate only) is captured in Technology &
Architecture Constraints. No obligation was removed or reversed — the contract's
constraints were already reflected here — which is why this is MINOR rather than
a MAJOR principle redefinition. Dangling references updated in AGENTS.md,
backend/app/schemas.py, docs/qm-alignment.md, and
.specify/specs/000-baseline/spec.md.

Amendment 2026-07-21 (1.0.0 → 1.0.1, PATCH): Link docs/architecture.md as the
authoritative system-context source from "Technology & Architecture Constraints"
(reference, not a copy, to prevent drift). No principle changed.

Version change: (unversioned template) → 1.0.0
Rationale: Initial ratification. The template placeholders are replaced with
concrete, project-derived principles for the first time, so this is a MAJOR
baseline (1.0.0) rather than an amendment.

Modified principles (placeholder → concrete):
  - [PRINCIPLE_1_NAME] → I. Contract Fidelity
  - [PRINCIPLE_2_NAME] → II. Layered, Backend-Owned Architecture
  - [PRINCIPLE_3_NAME] → III. Test-First Discipline (NON-NEGOTIABLE)
  - [PRINCIPLE_4_NAME] → IV. Deliberate Simplicity & Single-User Scope
  - [PRINCIPLE_5_NAME] → V. Kit-Aligned Consistency & Observability

Added sections:
  - Technology & Architecture Constraints (was [SECTION_2_NAME])
  - Development Workflow & Quality Gates (was [SECTION_3_NAME])

Removed sections: none.

Templates & docs reviewed for consistency:
  - .specify/templates/plan-template.md ...... ✅ aligned (Constitution Check
    gate references this file dynamically; no edits required)
  - .specify/templates/spec-template.md ...... ✅ aligned (no mandatory
    section added/removed by this constitution)
  - .specify/templates/tasks-template.md ..... ✅ aligned (test-first and
    quality tasks already representable)
  - .claude/skills/speckit-*/SKILL.md ........ ✅ reviewed; generic guidance,
    no outdated agent-specific references to fix
  - README.md / contract.md / docs/* ......... ✅ consistent; this constitution
    codifies existing contract.md constraints, adds no conflicts

Follow-up TODOs:
  - RATIFICATION_DATE is set to the first-fill date (2026-07-21). If the project
    recognises an earlier formal adoption date, amend it (PATCH bump).
-->

# kestrel Constitution

## Core Principles

### I. Contract Fidelity

This constitution is the authoritative record of the constraints an agent MUST
honour when changing the code. Every change MUST be consistent with it and MUST
NOT silently contradict it; any intentional departure from stack norms MUST be
recorded here (see Technology & Architecture Constraints), with its rationale,
before it is relied upon. The frontend/backend **type contract** MUST stay in
sync: business types in `frontend/src/types/` mirror the backend JSON shapes
they represent (e.g. `SessionSummary`, `SessionEvent`), and changing one side
without the other is prohibited.

**Rationale**: A single, version-controlled record prevents drift between the
backend and frontend and keeps deliberate deviations visible instead of tribal
knowledge.

### II. Layered, Backend-Owned Architecture

All business logic lives in the FastAPI backend (routers → services → stores),
with calls flowing downward only. The Vue/Vuetify frontend performs UX-only
client-side checks and MUST NOT be the sole enforcer of any rule that matters
for correctness or security. The database schema is owned exclusively by
Alembic: `Base.metadata.create_all()` and raw DDL (`CREATE TABLE`,
`ALTER TABLE`, interpolated SQL) in application code are prohibited.

**Rationale**: Keeping authority in the backend makes the system testable and
trustworthy regardless of the client, and Alembic-owned schema keeps migrations
reviewable and reversible.

### III. Test-First Discipline (NON-NEGOTIABLE)

Behaviour changes ship with tests: pytest for the backend, vitest for the
frontend. Tests are written to express the intended behaviour and MUST pass
before merge. Frontend tests MUST mock all HTTP calls; tests MUST NOT run
against a production database or a real `claude` subprocess. A bug fix starts
with a test that reproduces the bug.

**Rationale**: Tests are the executable specification of intended behaviour and
the only durable guard against regressions in a fast-moving alpha.

### IV. Deliberate Simplicity & Single-User Scope

kestrel is single-user by design. YAGNI governs: features, abstractions, and
dependencies are added only when a present need justifies them, and every new
npm/Python dependency MUST be justified. Single-user assumptions (e.g. no
multi-user auth) are intentional and MUST NOT be "fixed" by speculative
generalisation; the only planned access protection is a shared-secret gate, not
multi-user authentication. Added complexity MUST be recorded and justified (see
Governance).

**Rationale**: The project's value comes from being a focused personal tool;
unrequested generality is cost without benefit and erodes the contract.

### V. Kit-Aligned Consistency & Observability

Work follows the Quartermaster instruction kits resolved for the task
(`resolve_kits` per task, per `AGENTS.md`); the stack conventions those kits
encode are the default, and divergence MUST be justified. UI styling is
sourced from the Vuetify theme and design tokens — hard-coded hex/rgb/named CSS
colours are prohibited. The service stays observable: structured logging
(text or JSON) and health endpoints are maintained, and secrets are never
committed (`.env` stays out of version control; `.env.example` is the
documented template).

**Rationale**: Consistency across a two-language codebase and continuous
observability are what let a single maintainer move quickly without breaking
trust in the running system.

## Technology & Architecture Constraints

The living description of how the system fits together is
[`docs/architecture.md`](../../docs/architecture.md) — it is the source of truth
for system context and MUST NOT be duplicated here (a copy would drift). This
section records only the non-negotiable constraints an agent must honour.

- **Backend**: FastAPI (Python), managed with `uv`, in `backend/`.
  `pyproject.toml` is the dependency source of truth.
- **Frontend**: Vue 3 + Vuetify 4 + TypeScript (Vite, npm), in `frontend/`.
  `package.json` is the dependency source of truth. Components use the
  Composition API (`<script setup lang="ts">`).
- **Persistence**: SQLite via SQLAlchemy 2.x, schema owned by Alembic
  (`backend/alembic/`). Two deliberate, recorded deviations from the usual
  FastAPI/SQLAlchemy patterns are permitted and MUST be preserved unless this
  constitution is amended: stores own their `Session` lifecycle (a
  `sessionmaker(...).begin()` context per operation; no request-scoped `get_db`
  dependency), and timestamps are stored as naive UTC.
- **Worker agent**: the backend invokes the host's logged-in `claude` CLI as a
  subprocess (OAuth/Max subscription). No `ANTHROPIC_API_KEY` and no Agent SDK.
  Alternative backends (opencode, self-hosted LLM) are dispatched the same way.
- **Access model**: single concurrent user; the API is currently unauthenticated
  and bound to loopback. The only planned protection is a shared-secret access
  gate (see `docs/next-steps.md`), not multi-user authentication.
- **Run modes**: a bundled Docker image (backend + built SPA + `claude` CLI)
  and a run-from-source developer flow (uv / vite) MUST both remain working.

## Development Workflow & Quality Gates

- **Kit resolution**: call `resolve_kits(task="…")` at the start of each task
  and whenever the task's direction shifts, then pull sections on demand. Do
  not hard-code a fixed kit list.
- **Quality gates before merge**: backend and frontend test suites pass;
  linters/formatters pass with no suppressions added to dodge a real finding.
- **Documentation**: user-facing or behavioural changes update the relevant
  docs (`README.md`, `docs/*`) and, when binding constraints change, this
  constitution.
- **Security-first, minimal changes**: prefer the smallest change that solves
  the problem; ask before guessing at ambiguous requirements; never introduce
  hard-coded secrets or credentials.
- **Releases**: versioning follows CalVer with the channels documented in
  `docs/releasing.md`.

## Governance

This constitution supersedes ad-hoc practice for the topics it covers and is the
single authoritative record of the project's binding constraints; a conflict
between it and any other document is a defect to be resolved by amending this
constitution, not ignored.

- **Amendments** MUST be made by editing this file, documenting the change in
  the Sync Impact Report, and bumping the version.
- **Versioning policy** (semantic): MAJOR for backward-incompatible governance
  or principle removals/redefinitions; MINOR for a new principle/section or
  materially expanded guidance; PATCH for clarifications and non-semantic
  refinements.
- **Compliance**: every PR/review verifies the change complies with these
  principles. Any added complexity that appears to violate Principle IV MUST be
  justified in the change (e.g. the plan's Complexity Tracking table) with the
  simpler alternative and why it was rejected.
- **Runtime guidance**: `AGENTS.md` (and `CLAUDE.md`, which includes it) is the
  operational guidance for day-to-day development and MUST be kept consistent
  with this constitution.

**Version**: 1.1.0 | **Ratified**: 2026-07-21 | **Last Amended**: 2026-07-21

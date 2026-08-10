# Implementation Plan: Fixture Task Source & Rerun

**Branch**: `008-fixture-task-source` | **Date**: 2026-08-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `.specify/specs/008-fixture-task-source/spec.md`

## Summary

Kestrel's `TaskSource`/`CodeHost` ports (`backend/app/ports.py`, extracted in
feature 003) currently have two implementations, GitHub and Jira, both backed
by a live external tracker. This feature adds a third: a file-backed
**fixture** `TaskSource` for disposable local tasks that flow through the
same pipeline without ever touching a real ticket, reusing an existing
`CodeHost` (GitHub/GitLab) pointed at a real target repo. It adds a new
`visibility()` capability to `TaskSource` (`"public"` | `"private"`, same
static-capability shape as the existing `supports_time_spent()`) and a
**rerun** action — abandon, force-delete the branch, and immediately restart
against the same task, bypassing the poll wait — gated strictly on
`visibility() == "private"`, so it can never be exposed for a GitHub- or
Jira-originated run. Backend adds one new task-source type, one new poll
source, one new service method, and one new endpoint; frontend surfaces a
`rerunnable` flag (mirroring the existing `allow_incomplete_answers`
capability-flag pattern) and a Rerun button next to the existing
Clean-up/Abandon buttons. No new Alembic migration is required — `source`
and every touched schema field are already unconstrained/computed.

## Technical Context

**Language/Version**: Python 3.12+ (`backend/pyproject.toml`); TypeScript
(Vue 3, `frontend/package.json`).

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x (unchanged, no new
migration), pydantic 2.x — all already in use; no new backend dependency.
Frontend: Vue 3 Composition API, Vuetify 4 — no new frontend dependency.

**Storage**: SQLite via SQLAlchemy 2.x/Alembic (`backend/app/persistence/`) —
unchanged. New fixture-task data lives on the filesystem (one file per task
under an admin-configured `fixtures_dir`), not in the database — same
pattern as the existing worktree/`.kestrel/` artifact directories, not a new
storage technology.

**Testing**: pytest (backend), vitest (frontend). Per Constitution Principle
III, `FixtureTaskSource`/`FixturePollService` tests exercise real temp-dir
file I/O (no external subprocess/network boundary to mock, unlike the
`claude` CLI or GitHub/Jira HTTP clients) — the frontend Rerun button is
tested with HTTP mocked per existing convention.

**Target Platform**: Linux server / Docker (bundled image) and run-from-source
dev flow — both existing run modes, unaffected by this feature.

**Project Type**: Web service (FastAPI backend + Vue/Vuetify frontend) —
this feature touches both: backend for the new source/action, frontend for
the `rerunnable` flag and Rerun control.

**Performance Goals**: N/A beyond the spec's own constraint (SC-002: rerun
starts a fresh run within seconds, not after the poll interval) — satisfied
structurally by calling `ingestion.maybe_start_run` synchronously from the
new `rerun()` service method instead of waiting for the next scheduled poll.

**Constraints**: The safety property in spec User Story 3 — rerun MUST be
categorically unavailable for any run whose task source is `"public"` — is
enforced once, centrally, in the new `rerun()` service method (raising a
domain exception the router maps to 403), not duplicated per call site or
left to the frontend to enforce (Constitution Principle II: the frontend
button's `v-if` is a convenience, not the enforcement).

**Scale/Scope**: Single concurrent user (Constitution Principle IV); a
handful of fixture task files at a time — no scale engineering needed.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment |
|---|---|
| I. Contract Fidelity | **Requires a recorded amendment before implementation lands.** The public/private `visibility()` split and the rerun restriction it enforces are a genuinely new binding constraint (confirmed in `spec.md` Assumptions and the earlier design-plan research: no existing "append-only public source" principle exists today). Principle I requires it be recorded in the constitution, with rationale, before it is relied upon — tracked as a Phase 0/implementation deliverable below, not an afterthought. The frontend/backend type contract also gains one field (`rerunnable` on `WorkflowSummary`/`WorkflowDetail`) that MUST be added to both `backend/app/schemas.py` and `frontend/src/types/workflows.ts` together. |
| II. Layered, Backend-Owned Architecture | Pass. All new logic lives in `backend/app/services/` and `backend/app/routers/workflows.py`; the frontend's `rerunnable` check is UX-only (hides the button) — the actual guard lives server-side in the new `rerun()` method, matching Constraints above. No `create_all`/raw DDL; no schema change is needed at all (see Storage). |
| III. Test-First Discipline | Pass. New behavior (`FixtureTaskSource`, `FixturePollService`, `rerun()`'s visibility guard, the Rerun button's `v-if`) ships with pytest/vitest coverage before merge, per the spec's own Success Criteria (SC-001–SC-004) restated as tests. |
| IV. Deliberate Simplicity & Single-User Scope | Pass, with complexity justified in Complexity Tracking below. No plugin/registry framework is introduced — the fixture source is hand-wired in `bootstrap.py` exactly like Jira was (003-jira-ingestion's own spec explicitly rules out a registry). Code hosting is **not** reimplemented — the fixture source reuses an existing `CodeHost` (GitHub/GitLab) pointed at a real repo, per the maintainer's explicit choice over building a fully-offline local `CodeHost`. |
| V. Kit-Aligned Consistency & Observability | Pass. `resolve_kits` was called for this planning step (module-fastapi, stack-fastapi-vuetify, module-vue-vuetify, module-database-postgresql, module-design-principles, module-testing-strategy, module-code-structure-limits, module-version-control). The Rerun button follows the existing Vuetify icon-button pattern already used for Clean-up/Abandon (no new component library, no hard-coded colors). |

**Gate result**: PASS, conditional on the Principle I constitution amendment
(visibility/rerun constraint) being authored as part of this feature's
implementation, not deferred past it — same conditional-pass shape as
feature 006's hooks-mechanism amendment.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/008-fixture-task-source/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output
│   ├── rerun-endpoint.md
│   └── fixture-task-file.md
└── tasks.md              # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── ports.py                        # + TaskSource.visibility()
│   ├── config_models.py                # + TaskSourceConfig type="fixture", fixtures_dir
│   ├── services/
│   │   ├── github.py                   # GitHubTaskSource.visibility() -> "public"
│   │   ├── jira.py                     # JiraTaskSource.visibility() -> "public"
│   │   ├── fixture.py                  # NEW — FixtureTaskSource
│   │   ├── fixture_poll.py             # NEW — FixturePollService (PollSource)
│   │   ├── exceptions.py               # + RerunNotAllowedError
│   │   └── workflows/
│   │       ├── bootstrap.py            # register "fixture-issue" sources/code_hosts
│   │       ├── service.py              # + rerun(workflow_id)
│   │       └── poll_source.py          # register FixturePollService in configured_poll_sources()
│   ├── main.py                         # + RerunNotAllowedError -> 403 handler
│   ├── routers/workflows.py            # + POST /{workflow_id}/rerun; rerunnable in _detail()/_summaries()
│   └── schemas.py                      # + rerunnable: bool on WorkflowSummary/WorkflowDetail
└── tests/
    ├── test_fixture_task_source.py     # NEW
    ├── test_fixture_poll.py            # NEW
    └── test_workflow_rerun.py          # NEW

frontend/
├── src/
│   ├── types/workflows.ts              # + rerunnable: boolean
│   ├── composables/useWorkflows.ts     # + rerun(id)
│   └── components/WorkflowPanel.vue    # + Rerun v-btn, v-if="w.rerunnable"
└── tests/
    └── composables/useWorkflows.spec.ts  # extended with rerun() coverage

config.toml.example                     # document the fixture [[task_sources]] entry
.specify/memory/constitution.md         # Access-model amendment (Principle I): visibility/rerun
```

**Structure Decision**: Existing FastAPI backend layering (`routers → services
→ persistence`) is unchanged; `fixture.py`/`fixture_poll.py` are new,
narrowly-scoped modules (mirroring `jira.py`/`jira_poll.py`'s existing split)
rather than growing an existing file. No Alembic migration and no
`persistence/` changes — nothing new is persisted to the database by this
feature. Frontend changes are additive to three existing files, no new
component.

## Complexity Tracking

> Required by Principle IV governance: complexity that could look unjustified
> must be justified here, with the simpler alternative considered and why it
> was rejected.

| Added complexity | Why needed | Simpler alternative rejected because |
|---|---|---|
| New `visibility()` capability on the `TaskSource` protocol, plus a hard server-side gate in `rerun()` | Spec User Story 3 (P1, tied with User Story 1) requires rerun to be categorically unavailable for GitHub/Jira runs — a safety property, not a preference. | A config-toggle (`TaskSourceConfig.rerunnable: bool`) was considered and explicitly rejected during planning: it would let an admin misconfigure a public source into allowing rerun. A hardcoded per-implementation property removes that failure mode entirely. |
| New `FixturePollService` (a fourth `PollSource` implementation) rather than only wiring rerun's synchronous re-ingest path | Spec User Story 1 (P1) requires local tasks to be picked up by the normal scheduled check too, not only via rerun — rerun only makes sense once a first run already exists. | Skipping the poll source and requiring the admin to always trigger the first run manually (e.g. via a CLI command) was considered but rejected — it would special-case fixture tasks relative to every other source's "just works on the next poll" behavior, adding an inconsistent mental model for no real savings (the poll source is a small, mechanical mirror of the existing `ReconcileService`/`JiraPollService` shape). |
| Reusing a real GitHub/GitLab `CodeHost` for the fixture source (network calls to a real sandbox repo) instead of a fully-offline local `CodeHost` | Maintainer's explicit choice during planning: less new code, and the fixture source's actual goal is disposable *tickets*, not disposable *code hosting* — the existing `CodeHost` implementations already work and are already tested. | A fully-offline local `CodeHost` (bare repo, local change-request record) was the alternative on the table and was rejected in favor of this simpler reuse; it remains a documented option if a fully network-free fixture source is wanted later (YAGNI — not built until that need is concrete). |

## Phase 0 & Phase 1 outputs

See `research.md`, `data-model.md`, `contracts/*.md`, and `quickstart.md` in
this directory.

## Post-Design Constitution Check (re-evaluated after Phase 1)

Re-reading the Constitution Check table above against the completed
`data-model.md` and `contracts/*.md`: no new violations were introduced by
the detailed design beyond the one already flagged (Principle I amendment
for the visibility/rerun constraint). The Complexity Tracking table still
fully accounts for every new module/mechanism named in Project Structure —
no additional unjustified complexity was found during Phase 1 design work.
**Gate result: PASS**, same condition as before (constitution amendment must
land alongside implementation, not be deferred past it).

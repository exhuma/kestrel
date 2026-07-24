---
description: "Task list for Behavioral Verify Evidence"
---

# Tasks: Behavioral Verify Evidence

**Input**: Design documents from `.specify/specs/005-behavioral-verify-step/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: INCLUDED — Constitution III (Test-First Discipline, NON-NEGOTIABLE) makes tests
mandatory for every behaviour change. Every test mocks the backend/session (no real `claude`
subprocess, no real app process) per the existing pattern in `backend/tests/test_verify_loop.py`.

**Organization**: Grouped by user story. Boundary classification — the `WorkflowRun.boundary`
field, its persistence, `<BOUNDARY>` tag parsing, and `_design()` actually setting it — and the
extended verdict shape live in **Foundational**, since both user stories that follow need a real,
populated `run.boundary` and a verdict parser that can read self-reported observations. Priority
order: US1 (P1, the core behavioral-evidence loop), US2 (P2, hard gate vs. advisory feedback),
US3 (P3, audit-trail artifact). The coder TDD instruction (FR-010) isn't tied to a specific user
story's independent test, so it lives in Polish.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3
- All backend tests are flat `backend/tests/test_*.py`, matching this repo's existing layout.

---

## Phase 1: Setup

- [X] T001 [P] Add a note to `docs/configuration.md` near `verify_checks`/`max_verify_iterations`
      stating that this feature introduces no new dependency and no new config key — `boundary`
      is inferred by the `design` step, not operator-configured

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: `WorkflowRun.boundary` (field, column, migration, persistence, parsing, and the
`design` step actually setting it) and the extended verdict shape (`_parse_verdict` returning
`observations`) that both user stories build on.

**⚠️ CRITICAL**: No user story can start until this phase is complete.

- [X] T002 [P] Add `boundary: str | None = None` to `WorkflowRun` in `backend/app/models_workflow.py`
- [X] T003 [P] Add a nullable `boundary` `TEXT` column to `WorkflowRunRow` in `backend/app/persistence/tables.py`
- [X] T004 Create Alembic migration `backend/alembic/versions/0011_workflow_run_boundary.py`
      (`revision = "0011"`, `down_revision = "0010"` — once
      `feat/config-toml-and-workflow-ux` was reconciled into `master`, migrations 0009
      (`workflow_step_verify_round`) and 0010 (`notification_issue_number_nullable`) landed
      ahead of this one): add
      `workflow_run.boundary` (nullable, no backfill needed — every existing run simply gets
      `NULL`), with a working `downgrade()` (depends on T003)
- [X] T005 Persist and rehydrate `boundary` in `backend/app/persistence/workflow_store.py`
      (`save`'s upsert + `load_all`'s rebuild) (depends on T002, T003)
- [X] T006 [P] Extend `backend/tests/test_workflow_persistence.py`: a run's `boundary` round-trips
      through save/load and defaults to `None` when never set (depends on T005)
- [X] T007 Add `extract_boundary(text) -> str | None` to `backend/app/services/workflow_text.py`,
      mirroring the existing `extract_plan`/`extract_refined_issue` (`_extract_tag(text, "BOUNDARY")`),
      returning the tag's content only when it is exactly one of `"http"`, `"ui"`, `"both"`,
      `"none"` — anything else (including a missing tag) returns `None`
- [X] T008 [P] Write `backend/tests/test_workflow_text.py` coverage for `extract_boundary`: each of
      the four valid values, a missing tag, and an out-of-vocabulary value (the last two → `None`)
      (depends on T007)
- [X] T009 Extend `DESIGN_PROMPT` in `backend/app/services/workflows.py` with a
      `<BOUNDARY>http|ui|both|none</BOUNDARY>` tag instruction alongside the existing `<PLAN>`
      block; update `_design()` to parse it via `extract_boundary(result.final_text)` and set
      `run.boundary` — a missing or unparseable tag leaves `run.boundary` as `None` (matching
      `extract_boundary`'s own fallback) and MUST NOT fail the design step (depends on T002, T007)
- [X] T010 [P] Extend `backend/tests/test_workflow_service.py` with a `_design()` test: a
      well-formed `<BOUNDARY>` tag in the designer's response sets `run.boundary` to the matching
      value; a missing or malformed tag leaves `run.boundary` as `None` without failing the design
      step (depends on T009)
- [X] T011 Extend `_parse_verdict` in `backend/app/services/workflows.py` to additionally return a
      defensively-parsed `observations: list[Observation]` (drop malformed entries rather than
      raising; bound each `detail` to the same 2000-character cap `checks.py`'s module-level
      `_MAX_DETAIL` constant uses) — new signature
      `_parse_verdict(text) -> tuple[bool, str, list[Observation]]`; update its one existing call
      site in `_code_and_verify` to unpack three values (full use of the third value lands in US1)
- [X] T012 [P] Extend `backend/tests/test_verify_loop.py`'s `test_parse_verdict*` coverage: a
      verdict with a well-formed `observations` array parses correctly; a verdict with no
      `observations` key parses exactly as before (no regression on existing cases); a malformed
      entry inside `observations` is dropped, not treated as a parse failure (depends on T011)

**Checkpoint**: `boundary` is a real, persisted run field that `design` actually populates from a
`<BOUNDARY>` tag; `_parse_verdict` can read self-reported observations. No user-visible verify
behaviour has changed yet — `verify` doesn't consume `run.boundary` until US1.

---

## Phase 3: User Story 1 - Verify grounds acceptance in real, observed behavior (Priority: P1) 🎯 MVP

**Goal**: When a project has an HTTP or UI boundary, the verify step actually launches and
exercises the running, modified application — via a tool-enabled explore turn — before rendering
its verdict, and any failure it observes forces a rejection exactly like a failing configured check.

**Independent Test**: Run a project with a classified HTTP or UI boundary through
refine → design → code → verify. Confirm the verify round's evidence includes at least one
observation describing a real interaction with the running application before the run reaches
`done`.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, confirm they FAIL before implementing.

- [X] T013 [P] [US1] `backend/tests/test_verify_loop.py`: with `run.boundary="http"`, the verify
      round dispatches two turns — a tool-enabled explore turn, then a verdict turn that resumes
      the explore turn's session id
- [X] T014 [P] [US1] `backend/tests/test_verify_loop.py`: with `run.boundary="none"` (or unset),
      the explore turn is never dispatched — the verify round is exactly today's single
      `permission_mode="plan"` turn
- [X] T015 [P] [US1] `backend/tests/test_verify_loop.py`: a verdict's self-reported `observations`
      merge into the round's `Evidence.observations` alongside `CheckRunner`'s; one entry with
      `passed=False` forces `accept=False` even when the verdict's own `accept` field says `true`
      (the http/ui analogue of `test_failing_check_forces_reject`)
- [X] T016 [P] [US1] `backend/tests/test_verify_loop.py`: the explore-turn prompt text requires the
      agent to state explicitly when boundary-appropriate tooling is unavailable, rather than
      silently degrading to diff-only judgment (FR-007)

### Implementation for User Story 1

- [X] T017 [US1] Empirically determine the `permission_mode` value that runs the explore turn's
      Bash/MCP tool calls unattended against the real `claude` CLI (`research.md` R2 — try
      `"bypassPermissions"` first, headless with no TTY to approve a prompt); hardcode the
      confirmed value in `backend/app/services/workflows.py`
- [X] T018 [US1] Add an `EXPLORE_PROMPT` template to `backend/app/services/workflows.py`: carries
      PRD/design/diff/`{boundary}`/rendered check evidence; instructs launching and exercising the
      project per boundary (real HTTP requests for `http`/`both`; browser-driven interaction for
      `ui`/`both`); requires explicitly stating when boundary-appropriate tooling is unavailable
- [X] T019 [US1] Update `VERIFY_PROMPT` in `backend/app/services/workflows.py` to request the
      extended verdict shape (`accept`, `feedback`, `observations[]`) and to weigh self-reported
      observations the same as configured checks
- [X] T020 [US1] Wire the two-turn sequence into `_code_and_verify` in
      `backend/app/services/workflows.py`: when `run.boundary` is `"http"`/`"ui"`/`"both"`,
      dispatch the explore turn (permission_mode from T017) before the verdict turn, then resume
      that same session for the verdict turn (`permission_mode="plan"`, unchanged prompt
      discipline); when boundary is `"none"`/unset, go straight to today's single verdict turn
      (depends on T017, T018, T019)
- [X] T021 [US1] Merge the verdict's self-reported `observations` into `evidence.observations`
      before evaluating `evidence.all_passed()` in `_code_and_verify`, so the existing
      failing-observation invariant covers both `CheckRunner` and self-reported evidence uniformly
      (depends on T020)
- [X] T022 [US1] Run `backend/tests/test_verify_loop.py`, `test_workflow_reshape.py`, and
      `test_workflow_recovery.py`; confirm every `boundary=None`/no-observations path is unchanged
      from today's behaviour (depends on T013-T021)

**Checkpoint**: US1 fully functional and independently testable — this is the MVP.

---

## Phase 4: User Story 2 - Requirement conformance gates acceptance; code quality only advises (Priority: P2)

**Goal**: Verify's accept/reject decision is driven solely by requirement/design conformance
(behavioral + deterministic evidence); code-quality, maintainability, and documentation
observations are surfaced as feedback but never block acceptance on their own.

**Independent Test**: Produce an implementation that behaviorally satisfies the PRD (all checks
and observations pass) but has an identified code-quality shortcoming. Confirm the round is still
accepted, and the shortcoming appears in feedback.

### Tests for User Story 2 ⚠️

- [X] T023 [P] [US2] `backend/tests/test_verify_loop.py`: all checks and observations pass, the
      verdict's feedback text notes a code-quality concern, `accept=true` → the round is accepted
      and the concern still appears in feedback (locks in FR-006/SC-005)
- [X] T024 [P] [US2] `backend/tests/test_verify_loop.py`: a failing check or observation forces
      rejection even when the verdict's own text is otherwise positive about implementation
      quality (confirms the hard gate is never softened by advisory framing)

### Implementation for User Story 2

- [X] T025 [US2] Revise `VERIFY_PROMPT` in `backend/app/services/workflows.py`: instruct the
      verifier that `accept`/`reject` is decided solely by requirement conformance (behavioral +
      configured-check evidence); code-quality/maintainability/documentation observations belong
      in `feedback` and MUST NOT by themselves set `accept=false`
- [X] T026 [US2] Review `CODE_FEEDBACK_PROMPT` in `backend/app/services/workflows.py` and adjust
      wording if needed so a rejection's feedback clearly separates the conformance reason for
      rejection from any advisory notes

**Checkpoint**: US1 + US2 both independently functional.

---

## Phase 5: User Story 3 - What verify observed is recorded, without becoming a stale contract (Priority: P3)

**Goal**: Each run produces a committed, human-readable record of what its verify round(s) found,
kept as history — never re-checked by, or blocking, any other run's verify step.

**Independent Test**: Complete a run and confirm a human-readable verify record exists alongside
the run's other handover artifacts. Start a second, unrelated run against the same repository and
confirm its verify step is not affected by the first run's record.

### Tests for User Story 3 ⚠️

- [X] T027 [P] [US3] `backend/tests/test_verify_loop.py` (or a new `test_verify_report.py`): once a
      run reaches `done` or `escalated`, `.kestrel/<artifact_dir>/verify-report.md` exists in the
      fake worktree, containing round number, boundary, accept/reject, feedback, and the rendered
      observation list for **every** round the loop ran (not just the last one)
- [X] T028 [P] [US3] A test confirming a second, unrelated run against the same repo is unaffected
      by the first run's `verify-report.md` — no code path loads a prior run's report as verify
      input

### Implementation for User Story 3

- [X] T029 [US3] Add a report-rendering helper (e.g. `_render_verify_report(rounds)`) in
      `backend/app/services/workflows.py`, reusing the existing evidence-rendering logic already
      used to build the verify prompt
- [X] T030 [US3] In `_code_and_verify`, accumulate each round's summary (round number, boundary,
      accept/reject, feedback, evidence) into a list as the loop iterates; once the loop concludes
      (accept or escalate), render the full accumulated list via T029's helper and call
      `_write_artifact(run, "verify-report.md", ...)` once with the complete report (depends on T029)

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T031 [P] Strengthen `CODE_PROMPT` in `backend/app/services/workflows.py` with an explicit
      test-first / testing-pyramid instruction (FR-010)
- [X] T032 [P] `backend/tests/test_verify_loop.py` (or `test_workflow_service.py`): assert the
      rendered `CODE_PROMPT` text includes the TDD instruction (depends on T031)
- [X] T033 [P] Update `docs/architecture.md` to describe boundary classification, the two-turn
      explore/verdict pattern, and the explicit delegation of tool access to the operator's own
      backend
- [ ] T034 [P] Manually run `quickstart.md` Scenarios A-E against a local kestrel instance and
      record results (exploratory — not part of the automated suite). **Not done**: requires a
      live, logged-in `claude` CLI (with MCP tooling configured for the UI scenario) and a real
      target app to launch — unavailable in an automated implementation session. Left for the
      operator to run once the branch is deployed somewhere with that access.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: No dependency on Setup; BLOCKS all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational. No dependency on US2/US3.
- **User Story 2 (Phase 4)**: Depends on Foundational. Independently testable, but its prompt
  edits (T025) land in the same `VERIFY_PROMPT` region US1 touches (T019) — implement US1 first
  to avoid rebasing prompt text twice.
- **User Story 3 (Phase 5)**: Depends on Foundational and on US1's `_code_and_verify` shape
  (T020) existing, since T030 accumulates and writes from inside that same loop.
- **Polish (Phase 6)**: Depends on whichever stories are in scope for a given delivery being done.

### Within Each User Story

- Tests are written first and must fail before implementation (Constitution III).
- Foundational data/parsing before prompt changes before loop wiring before regression run.

### Parallel Opportunities

- T002 and T003 (different files: `models_workflow.py`, `tables.py`).
- All four US1 test tasks (T013-T016) target the same file
  (`backend/tests/test_verify_loop.py`) — write them as one sequential pass, not concurrently, to
  avoid merge conflicts; the `[P]` marker there reflects independence from *other* Foundational/US
  tasks, not from each other.
- T031 (docs) and T033 (docs) can run alongside any implementation task.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) + Phase 2 (Foundational).
2. Complete Phase 3 (US1) — behavioral evidence gathering and the extended invariant.
3. **STOP and VALIDATE**: run Quickstart Scenarios A/B/C manually against a real repo.
4. This alone already closes the core gap described in the feature's Context — everything after
   is refinement, not the core mechanism.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → validate independently → this is the MVP.
3. US2 → validate independently (tightens the accept/reject boundary; low risk, prompt-only).
4. US3 → validate independently (adds the audit trail; no behavior change to accept/reject).
5. Polish → coder TDD instruction, docs, quickstart pass.

---

## Notes

- `[P]` tasks touch different files with no dependency on an incomplete task.
- `[Story]` labels trace each task back to its user story for independent-delivery tracking.
- No task in this feature adds a new dependency or a new config key — verified by the empty
  Complexity Tracking table in `plan.md`.
- T017 (the `permission_mode` research spike) is the one task in this plan with a genuinely
  unknown outcome ahead of time; if `"bypassPermissions"` does not work as expected, this task is
  where that gets discovered and resolved before T018-T021 depend on it.
- T009/T010 (design sets `run.boundary`) were added during `/speckit-analyze` remediation — the
  first draft of this task list built the storage and parsing for `boundary` but never wired
  `_design()` to actually populate it, which would have made every downstream US1 task inert.
- The Alembic migration went through three numbers as the ground truth kept shifting: `0010`
  (planned against `feat/config-toml-and-workflow-ux`, not yet merged), then `0009` (implementation
  moved to a fresh branch off `master`, whose head was `0008` — that branch still hadn't merged),
  and finally `0011` (`feat/config-toml-and-workflow-ux` was reconciled into `master` afterward per
  explicit instruction, landing its own `0009`/`0010` first). Always verify the actual head in
  `backend/alembic/versions/` before creating a migration rather than trusting a number written
  down earlier — and re-verify after any late-breaking base-branch change.

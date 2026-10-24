# Tasks: CAB-2 estimates, coding/manual split, and executive summary

**Input**: Design documents from `specs/030-cab2-estimates-summary/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: required. Constitution Principle III makes them non-negotiable.
Each story's tests are written with or before its code.

**Order note**: US3 (estimation) is a hard prerequisite of US1 (the summary
is built from its output), so it is implemented first even though both are P1.
US2 and US4 are independent of each other.

## Phase 1: Setup

- [x] T001 Confirm a clean baseline: `task quality`, backend `uv run pytest -q`, frontend `npm test` all green before any change

## Phase 2: Foundational (blocks all stories)

- [x] T002 Add `CardKind.ESTIMATION = "estimation"` with a docstring comment in backend/app/models_board.py; add it to "Technical analysis" in backend/app/services/board/phases.py (R11)
- [x] T003 Exclude `estimation` from coordinator-creatable kinds in backend/app/services/board/coordinator.py, with a test in backend/tests/test_board_coordinator.py (R8)
- [x] T004 Replace the coordinator+gates `elif` chain in `_route_result` (backend/app/services/board/dispatch_ready.py) with a kind→router table; behaviour unchanged, existing dispatch tests green (R9)
- [x] T005 Create backend/app/services/board/candidate.py: `ClassifiedTask`, `Candidate`, `parse_candidate(text, strict)` and `candidate_to_json`, with type checks, id assignment and the duplicate-id rule (R4); `decomposition.py` re-exports what it needs
- [x] T006 [P] Tests for candidate parsing in backend/tests/test_board_candidate.py: strict (missing classification or summary, bad types, duplicate ids, id assignment full and partial) and lenient (legacy candidate defaults to coding)

## Phase 3: User Story 3 — Estimates from a separate specialist (P1)

**Goal**: a valid decomposition yields an `estimation` card for `developer`,
not a gate. Valid estimates open exactly one CAB-2 gate; invalid ones escalate.

**Independent test**: scripted pm and developer results. There is no gate
until estimation is accepted, then exactly one.

- [x] T007 [US3] Change `route_decomposition_result` in backend/app/services/board/decomposition.py to parse strictly, store the normalized `decomposition_candidate`, and create a READY `estimation` card (eligible `developer`, `read_only` workspace) with a dependency relation on the decomposition card; no gate
- [x] T008 [US3] Update backend/tests/test_board_decomposition.py: valid output → candidate plus estimation card plus edge and no gate; invalid (including missing classification or summary) → coordinator_review
- [x] T009 [US3] Create backend/app/services/board/estimation.py: `parse_estimates(text, candidate)` implementing contracts/estimation-output.md validation; `EstimationResultError`
- [x] T010 [US3] In estimation.py, `route_estimation_result(text, card, services…)`: read the candidate via the dependency edge; on success store `cab2_proposal`, create the gate "Approve decomposition (c coding, m manual)" targeting it, and store `executive_summary` produced by the gate card; on error, or when a gate is already awaiting, create coordinator_review (R6)
- [x] T011 [US3] Register the estimation route in the dispatch table, and add estimation extra context (the normalized candidate) in `_extra_context_for` in backend/app/services/board/dispatch_ready.py
- [x] T012 [US3] Tests in backend/tests/test_board_estimation.py: every validation rule, the success path (proposal content, gate title and target, summary artifact producer and trust), and the second-gate guard
- [x] T013 [P] [US3] Specialists: add `estimation` to backend/specialists/developer/manifest.toml; add an "On an estimation card…" section to developer/prompt.md; add classification and summary instructions to pm/prompt.md (a manual task's body is written for a human); update backend/specialists/README.md card kinds

## Phase 4: User Story 1 — Decide CAB-2 on an executive summary (P1)

**Goal**: the operator reads a code-built summary from the CAB-2 ask and
approves as before.

**Independent test**: totals equal the sums of the per-task figures, and the
summary opens from the banner and the rail with the agent_output chip.

- [x] T014 [US1] Create backend/app/services/board/exec_summary.py: pure `summary_totals(proposal)` and `render_executive_summary(proposal)` per data-model.md (header, prose, totals, risks, task table)
- [x] T015 [P] [US1] Tests in backend/tests/test_board_exec_summary.py: "2×S, 1×L", summed hours, tokens and review hours, low-confidence count, coding/manual split, risk grouping, no-risks case, formatting, and the no-recommendation header
- [x] T016 [US1] Frontend backend-less wiring: in frontend/src/lib/artifacts.ts map the `exec_summary` slot to `decomposition_gate`, drop `decomposition_gate` from `analysis` and add `estimation`; update the slot comment
- [x] T017 [US1] "Read executive summary" on an `approve_decomposition` ask in frontend/src/components/cockpit/ActionBanner.vue, opening `ArtifactDialog` on the gate card's `latest_artifact` (hidden when there is none, e.g. legacy gates)
- [x] T018 [P] [US1] Frontend tests: frontend/tests/lib/artifacts.test.ts (slot mapping) and an ActionBanner test for the summary button

## Phase 5: User Story 2 — Manual tasks are never handed to an agent (P1)

**Goal**: manual tasks are published with a marker and ingestion never
starts a workflow for them.

**Independent test**: approve one coding and one manual task. After
ingestion, one workflow exists.

- [x] T019 [P] [US2] Add `MANUAL_SENTINEL` and `ManualTaskSentinel` in backend/app/markers.py, and `has_manual_sentinel` in backend/app/services/task_source_utils.py
- [x] T020 [US2] `publish_decomposition` in backend/app/services/board/decomposition.py: lenient parse of the gate target; manual tasks get both sentinels plus the manual header; every task with an estimate gets the estimate section (data-model.md); legacy targets are unchanged (FR-019)
- [x] T021 [US2] `_start_via_board` in backend/app/services/ingestion.py: skip manual-marked bodies (`ingest outcome=skipped-manual`) before screening
- [x] T022 [US2] Tests: publish (sentinels, header, estimate section, legacy unchanged) in backend/tests/test_board_decomposition.py; ingestion skip on repeated polls in the ingestion tests

## Phase 6: User Story 4 — Read the original request (P2)

**Goal**: "Original request" in the rail opens `task_body` with a freshness
note and no trust chip.

**Independent test**: a snapshot with a body means the rail entry is
available and the dialog shows the note and no chip. The listing has no body.

- [x] T023 [US4] Backend plus frontend type contract in one commit: `BoardSnapshotOut.task_body` in backend/app/schemas.py, filled in backend/app/routers/board_views.py; `BoardSnapshot.task_body` in frontend/src/types/workflows.ts; amend specs/026-autonomous-work-board/contracts/board-api.md
- [x] T024 [US4] Backend API test: the snapshot has `task_body`, the workflow listing does not (backend/tests/test_board_api_additions.py)
- [x] T025 [US4] `railItems(cards, taskBody)` in frontend/src/lib/artifacts.ts: the request slot is available iff the body is non-empty and carries `directContent`; thread it through ArtifactRail.vue and RequestCockpitView.vue
- [x] T026 [US4] Direct-content mode in frontend/src/components/cockpit/ArtifactDialog.vue (`directContent` and `note` props: no fetch, no trust chip, `v-alert` note)
- [x] T027 [P] [US4] Frontend tests: the artifacts request slot, and an ArtifactDialog direct mode test (no fetch, note, no chip); update the types test if it pins shape

## Phase 7: Polish

- [x] T028 Update docs/architecture.md (the decomposition → estimation → CAB-2 flow, and the manual marker) and any operator doc that describes CAB-2
- [x] T029 Run `task quality`, the full backend and frontend tests, prettier and the frontend build (per the pre-push memory); fix any findings without suppressions
- [x] T030 File the follow-up GitHub issue (actual usage per attempt plus an estimate-vs-actual view) under epic #39, and link it from Vikunja 707

## Dependencies

- Phase 2 → everything.
- US3 (T007–T013) → US1 (T014–T018), because the summary is built in US3's
  route; T014 must exist before T010 can call it. **Practical order:** T014
  and T015 are done alongside T010.
- US2 (T019–T022) depends only on Phase 2 and T005.
- US4 (T023–T027) is independent of everything but Phase 1.

## Parallel opportunities

- T006, T013, T015, T018, T019 and T027 touch disjoint files.
- US4 can run fully in parallel with US3, US1 and US2. It shares only
  artifacts.ts with US1 (T016 and T025, sequential).

## Implementation strategy

This is one work package (Vikunja 707), delivered in commits per story so
each stays revertable:
1. Phase 2 + US3 + US1: the CAB-2 decision surface (the MVP, which ends the
   rubber stamp).
2. US2: the manual guard.
3. US4: the original request.
4. Polish.

## Implementation notes (2026-09-28)

- T001: the baseline had 2 failing tests, already there before this work,
  in `backend/tests/test_claude_backend.py`. A fake `_run` lacks the
  `on_queue_change` kwarg that `claude_cli.py` now passes. They are
  unrelated to this feature and were left alone.
- T030: the follow-up is GitHub #62 (sub-issue of epic #39).
- T016 note: the exec-summary rail slot and the banner button both read the
  gate card's `latest_artifact` (research R3). No DTO field was added for
  them.

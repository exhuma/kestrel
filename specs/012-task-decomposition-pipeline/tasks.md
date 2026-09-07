# Tasks: Task Decomposition Pipeline

**Input**: Design documents from `specs/012-task-decomposition-pipeline/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/,
quickstart.md (all present)

**Tests**: Included as first-class tasks — Constitution III ("Test-First
Discipline (NON-NEGOTIABLE)") requires every behaviour change to ship with
tests; this is not optional for this project.

**Organization**: Grouped by user story (spec.md P1/P2/P3). Note on
independence: this feature reshapes one linear pipeline
(`describe → refine → gap_analysis → design → …`), so — unlike a feature
adding parallel, unrelated surfaces — the three stories are genuinely
**sequential in the pipeline itself**, exactly as spec.md's own
"Independent Test" sections say ("Confirm an understanding (User Story 1),
**then** verify…"). Foundational installs the full six-step structure with
`describe`/`gap_analysis` as inert pass-throughs (observable pipeline
behaviour unchanged); each story phase then makes its own step's slice of
behaviour real and independently verifiable, and is deployable as an
increment on its own (US1 alone: kestrel double-checks its understanding,
nothing else changes; US1+US2: the PRD is business-only; US1+US2+US3: the
full decomposition pipeline).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no unresolved dependency)
- **[Story]**: Maps a task to US1/US2/US3 from spec.md

---

## Phase 1: Setup

**Purpose**: Confirm the existing toolchain is ready; no new project
structure or dependency is introduced (plan.md Technical Context).

- [X] T001 Confirm the backend (`uv sync`, from `backend/`) and frontend
      (`npm install`, from `frontend/`) toolchains are current, and the
      existing full test suite (`pytest`, `vitest`) passes clean before
      any change, as the regression baseline for this feature.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Install the full new six-step pipeline shape with the two new
steps as inert pass-throughs, so no user story starts from a broken
`continue_run()`.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Extend `Step` (backend/app/models_workflow.py) with
      `DESCRIBE = "describe"` and `GAP_ANALYSIS = "gap_analysis"`, and
      update `Step.sequence()` to return `[DESCRIBE, REFINE, GAP_ANALYSIS,
      DESIGN, CODE, VERIFY]` (data-model.md).
- [X] T003 [P] Add `"describing"` and `"analyzing"` to the `_TRANSIENT`
      set in backend/app/services/workflows/shared.py (data-model.md).
- [X] T004 Re-sequence `continue_run()` in
      backend/app/services/workflows/driver/__init__.py to walk
      `describe()` → `refine()` → `gap_analysis()` → `design()` →
      `code_and_verify()` → `deliver()` by step index (0-5), with an early
      `return` after `gap_analysis()` when it reports the run decomposed
      (mirrors the existing `if escalated: return` shape); add minimal
      `describe()`/`gap_analysis()` stubs that immediately mark their step
      `"done"` with an empty deliverable and report "not decomposed" (no
      real behaviour yet — restored by T008/T026); re-point `design()`'s
      PRD read from `run.steps[0].deliverable` to `run.steps[1]
      .deliverable` (research.md R6). Depends on: T002.
- [X] T005 [P] Add a foundational regression test in
      backend/tests/test_workflow_driver.py asserting: a run built via
      `WorkflowService.create()` now has 6 steps named
      `describe/refine/gap_analysis/design/code/verify` in that order, and
      an ordinary run (no `SUBTASK_SENTINEL`) reaches `done` exactly as
      before this feature (the two new steps are transparent pass-throughs
      at this point). Depends on: T002, T004.

**Checkpoint**: Full existing suite green; the pipeline is
behaviour-identical to before this feature except for two harmless new
step rows.

---

## Phase 3: User Story 1 - Confirm kestrel's understanding before any deeper work (Priority: P1) 🎯 MVP

**Goal**: Before any clarifying question is asked, kestrel restates its
understanding of the task and the requester confirms or amends it.

**Independent Test**: Submit a task with a deliberately ambiguous request;
confirm kestrel produces a restatement and that a correction changes what
it proceeds with (spec.md).

### Tests for User Story 1 ⚠️

- [X] T006 [P] [US1] Write gate-flow tests in
      backend/tests/test_workflow_describe.py (new file, mirroring
      test_workflow_gate.py's shape): a fresh run parks at
      `awaiting_describe_approval` before any interview question is asked;
      approving advances into `refining`; rejecting with feedback text
      produces a revised restatement and re-parks at
      `awaiting_describe_approval`; rejecting with no feedback ends the run
      `"rejected"` with a dismissal recorded (mirrors `refine`'s existing
      `_Rejected` contract); a restart mid-`"describing"` fails loudly
      (transient), a restart at `"awaiting_describe_approval"` re-parks
      with no duplicate notification.

### Implementation for User Story 1

- [X] T007 [P] [US1] Add `DESCRIBE_PROMPT` to
      backend/app/services/workflows/prompts.py: instructs the agent to
      read the ingested task and the surrounding codebase and produce a
      plain-language restatement of what it understands the task to be,
      wrapped in a delimiter tag the driver can extract (mirrors
      `DESIGN_PROMPT`'s `<PLAN>` pattern) — no questions, no
      implementation detail.
- [X] T008 [US1] Replace the T004 stub with a real `describe()` in
      backend/app/services/workflows/driver/__init__.py: run one agent
      turn with `DESCRIBE_PROMPT` against the fetched task body, extract
      the restatement, set `step.deliverable`, `run.status =
      "awaiting_describe_approval"`, and loop on
      `_Control`/`_Decision`/`await_gate`/`resolve`
      (backend/app/services/workflows/gate.py) exactly like `refine()`'s
      approve / reject-with-feedback / reject-without-feedback shape —
      reusing a `REFINE_FEEDBACK_PROMPT`-equivalent rewrite prompt for the
      amend path. Depends on: T004, T007. Makes T006 pass.
- [X] T009 [P] [US1] Add `"describing"` and `"awaiting_describe_approval"`
      status labels and a describe-step gate-approval UI (restatement
      text, approve/amend controls) to
      frontend/src/components/WorkflowPanel.vue, reusing the existing PRD
      approval UI pattern in the same file.
- [X] T010 [P] [US1] Extend
      frontend/tests/components/WorkflowPanel.states.test.ts with the new
      `describing`/`awaiting_describe_approval` states (label rendering,
      approve/amend controls present).

**Checkpoint**: The `describe` gate is fully live end-to-end; `refine`
onward is unchanged from today.

---

## Phase 4: User Story 2 - Get a non-technical, go/no-go requirements document (Priority: P2)

**Goal**: `refine`, reached only after `describe` is confirmed, restricts
itself to non-technical, requestor-altitude questions and produces a
go/no-go document with no implementation/architecture content.

**Independent Test**: Confirm an understanding (US1), then verify the
resulting document contains only business-level content and no
architecture/implementation language (spec.md).

### Tests for User Story 2 ⚠️

- [X] T011 [P] [US2] Add tests in backend/tests/test_profiles.py for a new
      business-altitude roster view (research.md R7): asserts it contains
      only `requester`/`pm`/`uiux` and excludes
      `developer`/`infosec`/`dba`/`architect`/`ops`.

### Implementation for User Story 2

- [X] T012 [US2] Add a business-altitude roster view to
      backend/app/profiles.py (e.g. a `roster_summary(profiles: Iterable
      [str])` restriction or a named `BUSINESS_ALTITUDE_IDS` constant —
      research.md R7 leaves the exact shape to implementation). Makes
      T011 pass.
- [X] T013 [US2] Wire `refine`'s call sites
      (backend/app/services/workflows/interview/__init__.py
      `coordinator_profiles`, backend/app/services/workflows/interview/
      questions.py `generate_questions`) to pass the business-altitude
      roster view instead of the full roster when driven through this
      pipeline. Depends on: T012. Makes T014 pass.

### Wiring verification for User Story 2 ⚠️

- [X] T014 [P] [US2] Add a test in backend/tests/test_workflow_interview.py
      (written before T012/T013 land; expected to fail until they do)
      asserting that when `refine` is driven through this pipeline, the
      coordinator is invoked with the business-altitude roster only (not
      the full `roster_summary()`), and the resulting refined document
      contains no technical/implementation-flavoured content markers.

**Checkpoint**: `refine` now always produces a business-only PRD;
`gap_analysis` is still the T004 stub, so the pipeline still ends at
`design`/`code`/`verify`/`deliver` exactly as before this feature.

---

## Phase 5: User Story 3 - Get independently implementable follow-up tasks instead of a black-box implementation (Priority: P3)

**Goal**: Once the PRD is approved, `gap_analysis` produces a
technical-analysis summary and self-contained follow-up tasks published to
the task source, ends the run, and a later-promoted follow-up task fast-
paths straight to `design`.

**Independent Test**: Approve a requirements document (US2); verify a
technical-analysis summary and follow-up tasks appear in the tracker, each
self-contained; verify the original run ends at `gap_analysis` without
reaching `design`; verify creating the follow-up tasks starts no new run;
verify a later-triggered follow-up task skips straight to `design`
(spec.md).

### Tests for User Story 3 ⚠️

- [X] T015 [P] [US3] Add `create_subtask` contract tests in
      backend/tests/test_github_ports.py: a created follow-up issue's body
      contains the self-contained content plus `SUBTASK_SENTINEL`, and it
      is created **without** the configured `trigger_label`
      (contracts/task-source-subtask-port.md).
- [X] T016 [P] [US3] Add `create_subtask` contract tests in
      backend/tests/test_jira_client.py: the created follow-up issue uses
      Jira's native `Sub-task` issue type with the parent field set to the
      originating ticket, body carries `SUBTASK_SENTINEL`.
- [X] T017 [P] [US3] Add `create_subtask` contract tests in
      backend/tests/test_fixture_task_source.py: a new fixture task file
      is written with a `parent` field pointing at the originating task's
      ref, body carries `SUBTASK_SENTINEL`.
- [X] T018 [P] [US3] Add tests in backend/tests/test_workflow_gap_analysis.py
      (new file) per contracts/gap-analysis-output.md: an indivisible
      approved document still yields exactly one published follow-up task
      plus a technical-analysis summary (never zero); a follow-up task
      that fails the self-containment check is revised and re-checked
      before publishing; `gap_analysis` completing successfully always
      results in `run.status == "decomposed"`, never `"designing"`; a
      `create_subtask` failure after the self-containment gate passed
      fails the run rather than publishing a partial set; the
      technical-analysis summary is published to the *original* ticket
      (spec.md FR-012), verified as a distinct call from the per-follow-up
      `create_subtask` calls.
- [X] T019 [P] [US3] Add sentinel fast-path tests: unit tests for
      `SUBTASK_SENTINEL`/its helpers in backend/tests/test_workflow_text.py
      (mirroring the existing `has_sentinel`/`append_sentinel` tests), and
      a `drive()`-level test in backend/tests/test_workflow_driver.py
      asserting a task body carrying `SUBTASK_SENTINEL` pre-marks
      `describe`/`refine`/`gap_analysis` `"done"` and the run reaches
      `"designing"` directly.

### Implementation for User Story 3

- [X] T020 [P] [US3] Add `create_subtask(self, parent_ref: str, title:
      str, body: str) -> str` to the `TaskSource` Protocol in
      backend/app/ports.py (data-model.md).
- [X] T021 [US3] Implement `GitHubClient.create_issue` and
      `GitHubTaskSource.create_subtask` in backend/app/services/github.py:
      creates a new issue in the same repo, body prefixed with a
      `Sub-task of #<parent-number>` reference line plus
      `SUBTASK_SENTINEL`, created without the source's `trigger_label`.
      Depends on: T020. Makes T015 pass.
- [X] T022 [US3] Implement Jira sub-task creation in
      backend/app/services/jira.py (`JiraClient` create method +
      `JiraTaskSource.create_subtask`): native `Sub-task` issue type,
      parent field set, body carries `SUBTASK_SENTINEL`. Depends on: T020.
      Makes T016 pass.
- [X] T023 [US3] Implement `FixtureTaskSource.create_subtask` in
      backend/app/services/fixture.py: writes a new JSON task file under
      the configured `fixtures_dir` with a `parent` field and
      `SUBTASK_SENTINEL` in the body. Depends on: T020. Makes T017 pass.
- [X] T024 [P] [US3] Add `SUBTASK_SENTINEL` and its
      `has_subtask_sentinel`/`append_subtask_sentinel` helpers to
      backend/app/services/workflow_text.py, alongside the existing
      `SENTINEL`/`has_sentinel`/`append_sentinel` (data-model.md). Makes
      part of T019 pass.
- [X] T025 [US3] Add the `gap_analysis` prompt set to
      backend/app/services/workflows/prompts.py: a technical-profile
      analysis/generation prompt, a reconcile/synthesis prompt producing
      the technical-analysis summary plus candidate follow-up tasks, and a
      self-containment completeness-critic prompt (mirrors
      `CRITIC_PROMPT`'s shape, contracts/gap-analysis-output.md).
- [X] T026 [US3] Replace the T004 stub with a real `gap_analysis()` in
      backend/app/services/workflows/driver/__init__.py: fan out to the
      technical-altitude profiles (T012's roster-view mechanism, technical
      side), reconcile into the technical-analysis document and candidate
      follow-up tasks, run the self-containment critic and revise any
      failing task before publishing, write the `technical-analysis.md`
      artifact (backend/app/services/workflows/artifacts.py's existing
      `write_artifact`), call `create_subtask` once per follow-up task,
      publish the summary to the original ticket, set `run.status =
      "decomposed"`, and report "decomposed" to `continue_run()`. A
      failure anywhere after the self-containment gate passed (e.g. one
      `create_subtask` call) fails the run rather than silently
      publishing a partial set. Depends on: T004, T012, T021, T022, T023,
      T025. Makes T018 pass.
- [X] T027 [US3] Confirm/adjust `continue_run()`'s early-return branch
      (added as a stub in T004) now correctly short-circuits on the real
      `gap_analysis()` "decomposed" report in
      backend/app/services/workflows/driver/__init__.py. Depends on: T026.
- [X] T028 [US3] Extend `drive()` in the same driver module with the
      `SUBTASK_SENTINEL` fast-path branch (research.md R5): when the
      fetched task body carries `SUBTASK_SENTINEL`, pre-mark `describe`/
      `refine`/`gap_analysis` steps `"done"` and seed `run.steps[1]
      .deliverable` (design's PRD input, per T004's re-index) with the
      follow-up task's own body. Depends on: T024, T004. Makes the rest of
      T019 pass.
- [X] T029 [P] [US3] Add `"analyzing"` and `"decomposed"` status labels
      (and a technical-analysis-summary indicator) to
      frontend/src/components/WorkflowPanel.vue.
- [X] T030 [P] [US3] Update docs/architecture.md's "Design trade-offs"
      section for the extended pipeline, and add operator guidance to
      docs/setup-jira-workflow.md on scoping `jql` to exclude newly
      created follow-up sub-tasks (research.md R4).

**Checkpoint**: All three user stories work end-to-end; the full pipeline
and the follow-up-task fast path are both live.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T031 [P] Run every `quickstart.md` scenario (1-4) end-to-end against
      a fixture task source and confirm each "Expect" holds; each scenario
      validates its corresponding SC-00N from spec.md (see quickstart.md
      annotations).
- [X] T032 [P] Run `task quality`; if
      frontend/src/components/WorkflowPanel.vue now exceeds a structural
      limit from the T009/T029 additions, extract the gate-approval UI
      into a sub-component rather than suppressing the check (per
      AGENTS.md's guardrails — ask before overriding any limit).
- [X] T033 Run the full backend (`pytest`) and frontend (`vitest`) suites
      once more end-to-end as the final regression pass.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
  (T004 requires T002; nothing in `continue_run()` is safely callable
  before it).
- **User Story 1 (Phase 3)**: Depends on Foundational only.
- **User Story 2 (Phase 4)**: Depends on Foundational only (not on US1's
  `describe()` implementation — T012/T013 touch `profiles.py`/
  `interview/`, disjoint from T007/T008's `prompts.py`/`describe()`). May
  be implemented in parallel with US1 by a second developer, though in the
  live pipeline `refine` is only *reached* after `describe` (US1) approves.
- **User Story 3 (Phase 5)**: Depends on Foundational; T026
  (`gap_analysis()`) depends on T012 (US2's altitude-roster mechanism,
  reused for the technical side) — so US3's implementation tasks depend on
  US2's T012 landing first, even though US3's test/port tasks (T015-T025
  except T012's consumer) do not.
- **Polish (Phase 6)**: Depends on all three stories.

### Within Each Story

- Tests (T006, T011/T014, T015-T019) are written first and must fail
  before their corresponding implementation task lands.
- Port/protocol changes (T020) before per-source implementations
  (T021-T023).
- Driver stubs (T004) before real step implementations (T008, T026).

### Parallel Opportunities

- T003 alongside T002 (different files).
- T006, T007 in parallel (test file vs. prompts file); T009/T010 in
  parallel with each other and with T006-T008 (frontend vs. backend).
- T011 alongside Foundational-complete work; T014 waits on nothing but can
  be written before T012/T013 land (it's expected to fail first).
- T015, T016, T017, T018, T019 are all different files — fully parallel.
- T021, T022, T023 touch three different source files — parallel once
  T020 lands.
- T024 alongside T020-T023 (different file).
- T029, T030 in parallel with each other and with T020-T028 (frontend/docs
  vs. backend).

---

## Parallel Example: User Story 3

```bash
# Once Foundational + T012 (US2) are done, launch US3's tests together:
Task: "create_subtask contract tests in backend/tests/test_github_ports.py"
Task: "create_subtask contract tests in backend/tests/test_jira_client.py"
Task: "create_subtask contract tests in backend/tests/test_fixture_task_source.py"
Task: "gap_analysis output tests in backend/tests/test_workflow_gap_analysis.py"
Task: "SUBTASK_SENTINEL fast-path tests in test_workflow_text.py / test_workflow_driver.py"

# Then launch the three per-source create_subtask implementations together:
Task: "GitHubTaskSource.create_subtask in backend/app/services/github.py"
Task: "JiraTaskSource.create_subtask in backend/app/services/jira.py"
Task: "FixtureTaskSource.create_subtask in backend/app/services/fixture.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1).
2. **STOP and VALIDATE**: run Scenario 1 of `quickstart.md` against a
   fixture task; confirm the understanding-checkpoint gate works and
   everything past `refine` is unaffected.
3. Deploy/demo if ready — this alone is real, shippable value (spec.md
   User Story 1's own framing).

### Incremental Delivery

1. Setup + Foundational → pipeline shape ready, behaviour unchanged.
2. Add US1 → validate Scenario 1 → deploy (understanding-checkpoint live).
3. Add US2 → validate Scenario 2 → deploy (PRD is now business-only).
4. Add US3 → validate Scenarios 3-4 → deploy (full decomposition +
   fast path live).
5. Polish.

### Parallel Team Strategy

Once Foundational is done: Developer A takes US1 (T006-T010); Developer B
takes US2 (T011-T014) — genuinely disjoint files from US1; US3's test/port
tasks (T015-T020, T024) can start immediately after Foundational too, but
its `gap_analysis()` implementation (T026) waits on US2's T012 landing.

---

## Notes

- [P] tasks touch different files with no unresolved dependency.
- Tests are mandatory here (Constitution III), not optional — write them
  first, watch them fail, then implement.
- Commit after each task or logical group; stop at any checkpoint to
  validate a story independently.
- No task in this list adds a database migration or a new runtime
  dependency (research.md R10, plan.md Technical Context) — if
  implementation reveals one is actually needed, stop and reconcile with
  plan.md before proceeding, per this project's quality-override
  discipline (AGENTS.md).

# Tasks: Feedback Intake

**Input**: Design documents from `specs/013-feedback-intake/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/,
quickstart.md (all present)

**Tests**: Included as first-class tasks — Constitution III ("Test-First
Discipline (NON-NEGOTIABLE)") requires every behaviour change to ship with
tests; not optional for this project.

**Organization**: Grouped by user story (spec.md P1-P4). As with feature
012, these stories are **not fully independent slices**: US2 extends US1's
dispatch branch with the queued/no-gate case, US3 adds new capabilities
(PR reads, branch resume, triage) that US4's revive/escalated paths directly
reuse. Each is still independently *testable and demoable* once its own
phase lands (US1 alone: a parked run redirects from a ticket comment,
nothing else changes), and each is a deployable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no unresolved dependency)
- **[Story]**: Maps a task to US1/US2/US3/US4 from spec.md

---

## Phase 1: Setup

- [ ] T001 Confirm the backend (`uv sync`, from `backend/`) toolchain is
      current and the existing full test suite (`pytest`) passes clean
      before any change, as the regression baseline for this feature.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Install the shared plumbing every user story dispatches
through — persistence, the port's read shape, config, and the marker gate.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Migration `backend/alembic/versions/0015_feedback.py`: add
      `feedback_item` (PK `external_id`, `workflow_id` nullable FK,
      `task_ref`, `origin`, `author`, `body`, `state`, `target_step`
      nullable, `created_at`, `processed_at` nullable, index
      `(workflow_id, state)`) and `feedback_cursor` (PK `scope`, `cursor`,
      `updated_at`) tables, plus nullable `workflow_run.pr_number
      INTEGER`. Corresponding `FeedbackItemRow`/`FeedbackCursorRow` +
      `WorkflowRunRow.pr_number` in `backend/app/persistence/tables.py`
      (data-model.md).
- [X] T003 `backend/app/persistence/feedback_store.py::FeedbackStore`
      (`claim`, `queued_for`, `mark`, `cursor`, `set_cursor`) +
      `get_feedback_store()`. Depends on T002.
- [X] T004 [P] `Feedback` dataclass + `TaskSource.list_comments`/
      `acknowledge` on the protocol in `backend/app/ports.py`
      (contracts/feedback-source-port.md).
- [X] T005 [P] Config settings `feedback_marker` (default `@kestrel`),
      `feedback_ignore_authors`, `feedback_window_days` (default 14) in
      `backend/app/config.py`.
- [X] T006 [P] `backend/app/services/feedback/marker.py`: whole-token
      case-insensitive marker match + author-denylist/Bot-type guard
      (research.md R1, R6).
- [X] T007 [P] Foundational tests: migration applies cleanly and rolls
      back, `FeedbackStore` claim/mark/cursor round-trip
      (`backend/tests/test_feedback_store.py`), marker/author-guard unit
      tests (`backend/tests/test_feedback_marker.py`). Depends on
      T002-T006.

**Checkpoint**: Persistence, port shape, and the marker gate exist; no
transport or dispatch logic yet.

---

## Phase 3: User Story 1 - Redirect a parked run from the ticket (Priority: P1) 🎯 MVP

**Goal**: A marked ticket comment on a run parked at a gate is applied
exactly as a UI reject-with-feedback would be.

**Independent Test**: quickstart.md Scenario 1.

### Tests for User Story 1 ⚠️

- [X] T008 [P] [US1] `list_comments`/`acknowledge` contract tests for
      GitHub in `backend/tests/test_github_ports.py` (cursor round-trip;
      `acknowledge` hits the reactions endpoint).
- [X] T009 [P] [US1] Same for Jira in `backend/tests/test_jira_client.py`
      (`acknowledge` always returns `False`, never raises).
- [X] T010 [P] [US1] Same for fixture in
      `backend/tests/test_fixture_task_source.py`: reads
      `<slug>.comments.jsonl`; asserts it never reads `<slug>.log` (the
      self-feedback-loop trap, research.md R1); `acknowledge` always
      `False`.
- [X] T011 [P] [US1] `FeedbackIntakeService` pipeline tests in
      `backend/tests/test_feedback_intake.py`: marker gate, author-guard,
      claim/dedup on a race, routing to the newest run for a `task_ref`.
- [X] T012 [P] [US1] `FeedbackDispatcher` gate-branch tests in
      `backend/tests/test_feedback_dispatch.py`:
      `awaiting_describe_approval`/`awaiting_refine_approval` →
      `service.reject(refinement_prompt=...)`; a second identical marked
      comment on the still-parked run does not re-fire.
- [X] T013 [P] [US1] Webhook `issue_comment` handling test (ticket-origin
      only — no `pull_request` key on the payload) in
      `backend/tests/test_github_webhook.py` (extend).
- [X] T014 [P] [US1] Poll-transport test in
      `backend/tests/test_feedback_poll.py`: walks non-terminal runs,
      calls `list_comments(since=cursor)`, advances the cursor.

### Implementation for User Story 1

- [X] T015 [P] [US1] `GitHubClient.list_issue_comments` +
      `GitHubTaskSource.list_comments`/`acknowledge` in
      `backend/app/services/github.py`. Depends on T004. Makes T008 pass.
- [X] T016 [P] [US1] `JiraClient.list_comments` +
      `JiraTaskSource.list_comments`/`acknowledge→False` in
      `backend/app/services/jira.py`. Depends on T004. Makes T009 pass.
- [X] T017 [P] [US1] `FixtureTaskSource.list_comments`/`acknowledge→False`
      in `backend/app/services/fixture.py`. Depends on T004. Makes T010
      pass.
- [X] T018 [US1] `backend/app/services/feedback/intake.py::
      FeedbackIntakeService` (marker → author-guard → claim → route →
      persist `queued` → best-effort acknowledge). Depends on T003, T005,
      T006, T015-T017. Makes T011 pass.
- [X] T019 [US1] `backend/app/services/feedback/dispatch.py::
      FeedbackDispatcher`, gate-branch only. Depends on T018. Makes T012
      pass.
- [X] T020 [P] [US1] Extend `backend/app/routers/github_webhook.py` with
      the `issue_comment` event (ticket-origin branch only for now) +
      `backend/app/services/feedback/github_events.py` per-event demux
      helper (keeps the router thin). Depends on T019. Makes T013 pass.
- [X] T021 [P] [US1] `backend/app/services/feedback/poll.py::
      FeedbackPollService` (existing `PollSource` protocol) + register in
      `backend/app/services/poll_source.py`. Depends on T019. Makes T014
      pass.

**Checkpoint**: A marked ticket comment redirects a parked run end-to-end,
via both webhook (GitHub) and poll (Jira/fixture).

---

## Phase 4: User Story 2 - Steer an actively-working run from the ticket (Priority: P2)

**Goal**: Feedback with no open gate to land on is queued and applied at
the next round/step boundary — never mid-turn.

**Independent Test**: quickstart.md Scenario 2.

### Tests for User Story 2 ⚠️

- [X] T022 [P] [US2] `FeedbackDispatcher` transient-branch test (extend
      `test_feedback_dispatch.py`): `coding`/`verifying`/`analyzing`/
      `designing`/`describing`/`refining`/`opening_pr` all stay `queued`,
      never dispatched immediately.
- [X] T023 [P] [US2] `drain_feedback` boundary tests: consumed at the top
      of a `code_and_verify` round
      (`backend/tests/test_workflow_driver_code_verify.py`, extend) and at
      the top of `continue_run` between steps
      (`backend/tests/test_workflow_driver.py`, extend); an in-progress
      turn is never interrupted.

### Implementation for User Story 2

- [X] T024 [US2] `drain_feedback(service, run)` in
      `backend/app/services/feedback/dispatch.py`. Depends on T019.
- [X] T025 [P] [US2] Wire `drain_feedback` into `code_and_verify`'s
      round-start in
      `backend/app/services/workflows/driver/code_verify.py`. Depends on
      T024. Makes part of T023 pass.
- [X] T026 [P] [US2] Wire `drain_feedback` into `continue_run`'s
      between-step boundary in
      `backend/app/services/workflows/driver/__init__.py`. Depends on
      T024. Makes the rest of T023 pass.

**Checkpoint**: US1+US2 — feedback is never lost regardless of what phase
the run is in.

---

## Phase 5: User Story 3 - Amend the same pull/merge request from review feedback (Priority: P3)

**Goal**: Review feedback resumes the *same* branch; a triage turn decides
which step to re-enter at, including re-opening a gate when warranted.

**Independent Test**: quickstart.md Scenario 3.

### Tests for User Story 3 ⚠️

- [X] T027 [P] [US3] `ChangeRequest` + `get_change_request`/
      `list_review_comments`/`acknowledge`/`change_request_number`
      contract tests for GitHub in `test_github_ports.py` (origin-tagged
      `external_id` for conversation vs. review comments; `acknowledge`
      picks the matching endpoint).
- [X] T028 [P] [US3] Same for GitLab in the existing GitLab test file
      (`acknowledge` via `award_emoji`).
- [X] T029 [P] [US3] `change_request_number` pure-function tests
      (well-formed and malformed/garbage URLs) alongside the port tests.
- [X] T030 [P] [US3] `add_worktree_existing` tests in
      `backend/tests/test_git_service.py` (extend): resumes the local ref
      when the mirror holds it; falls back to `-b <branch> ...
      origin/<branch>` after a refetch when it doesn't.
- [X] T031 [P] [US3] `rewind_to` tests, one per legal target step, in
      `backend/tests/test_workflow_reentry.py` (new): before/target/after
      status partitioning, `session_id` cleared only after the target,
      earlier deliverables untouched.
- [X] T032 [P] [US3] `extract_feedback_triage` tests (well-formed tag,
      malformed tag, unrecognized `step` — both fall back to `code` +
      log) in `backend/tests/test_workflow_text.py` (extend).
- [X] T033 [US3] End-to-end resume test in
      `backend/tests/test_workflow_feedback_resume.py` (new): `done` run
      + open PR + review feedback → same branch resumed
      (`add_worktree_existing`, not `add_worktree`), `deliver()` pushes
      without a second `open_change_request`, exactly one landing comment.
- [X] T034 [US3] Triage step-selection tests (same new file): an
      implementation-only comment selects `code`; an approach-questioning
      comment selects `design` or earlier and re-parks if that step is
      gated.

### Implementation for User Story 3

- [X] T035 [US3] `ChangeRequest` dataclass + `CodeHost` protocol
      extension in `backend/app/ports.py`. Depends on T004.
- [X] T036 [P] [US3] `GitHubClient.get_pull_request`/`list_pull_reviews`/
      `list_pull_review_comments` + `GitHubCodeHost.get_change_request`/
      `list_review_comments`/`acknowledge` (merging conversation + review
      comments, origin-tagged) + `change_request_number` in
      `backend/app/services/github.py`. Depends on T035. Makes T027, T029
      pass.
- [X] T037 [P] [US3] `GitLabCodeHost.get_change_request`/
      `list_review_comments`/`acknowledge` (via `award_emoji`) in
      `backend/app/services/gitlab.py`; gitea path returns `[]`. Depends
      on T035. Makes T028 pass.
- [X] T038 [P] [US3] `GitService.add_worktree_existing` + shared
      `_worktree_add` helper in `backend/app/services/git.py`. Makes T030
      pass.
- [X] T039 [P] [US3] `backend/app/services/workflows/reentry.py::
      rewind_to` (pure function). Makes T031 pass.
- [X] T040 [P] [US3] `FEEDBACK_TRIAGE_PROMPT` in
      `backend/app/services/workflows/prompts_feedback.py` (new — keeps
      `prompts.py` under its 500-line ceiling) + `extract_feedback_triage`
      in `backend/app/services/workflow_text.py`. Makes T032 pass.
- [X] T041 [US3] `backend/app/services/feedback/triage.py` (runs the
      prompt, parses via `extract_feedback_triage`, defaults to `code` on
      a parse miss). Depends on T040.
- [X] T042 [US3] Set `workflow_run.pr_number` in `deliver()`; make
      `deliver()` idempotent when `pr_number` is already open (push only —
      no second `open_change_request` — one landing comment) in
      `backend/app/services/workflows/driver/__init__.py`. Depends on
      T036.
- [X] T043 [US3] `backend/app/services/workflows/driver/resume.py`
      (mirror ensure → `add_worktree_existing` → `_ensure_artifact_dir` →
      `rewind_to` → `continue_run`). Depends on T038, T039, T041, T042.
      Makes T033, T034 pass.
- [X] T044 [US3] `FeedbackDispatcher` review-origin routing: resolve
      `run.pr_number` (fall back to `pr_url` containment), route open-PR
      review feedback to `resume.resume_with_feedback`. Depends on T043.
- [X] T045 [US3] Extend `github_webhook.py`/`github_events.py` with
      `pull_request_review`, `pull_request_review_comment`, and
      `issue_comment`'s PR-conversation branch (payload's `pull_request`
      key). Depends on T044.

**Checkpoint**: US1+US2+US3 — review feedback amends the same PR at the
right re-entry point.

---

## Phase 6: User Story 4 - Pick up feedback after a run has already finished (Priority: P4)

**Goal**: `done` → revive if resumable else linked successor; `escalated` →
resume from base; `decomposed` → correction, never a re-split.

**Independent Test**: quickstart.md Scenario 4.

### Tests for User Story 4 ⚠️

- [X] T046 [US4] Revive-vs-successor tests (extend
      `test_feedback_dispatch.py`): `done` + open PR → same run resumes;
      `done` + merged/closed PR → a linked successor run is started,
      carrying parent lineage. **Deviation from the literal task text**:
      the successor is started via a new `IngestionService.
      start_successor_run()`, not by calling `maybe_start_run` directly —
      see the note under T050 below for why `maybe_start_run` itself
      cannot be reused unmodified on this branch.
- [X] T047 [US4] `escalated` resume test (same file): `add_worktree`
      (fresh, base branch) used, not `add_worktree_existing`; the triage
      instruction is carried into the retry.
- [ ] T048 [US4] `decomposed` correction test (same file):
      `create_subtask` called exactly once via `publish_correction`;
      `run_gap_analysis` is never invoked. **Blocked, left unchecked**:
      this branch is based on master, not feature 012. There is no
      `decomposed` status in `models_workflow.Step`/`_TERMINAL_STATUSES`
      here, and `TaskSource` (`app/ports.py`) has no `create_subtask`
      method — the entire gap-analysis/decomposition pipeline this task
      depends on does not exist yet on this branch. Building it here
      would mean inventing a fake status and a fake port method with no
      real caller, which the task brief explicitly says not to do. Revisit
      once feature 012 merges.

### Implementation for User Story 4

- [X] T049 [US4] Run-lineage field (parent run id) on a linked successor —
      smallest viable shape per data-model.md's "Run lineage" entity:
      `WorkflowRun.parent_run_id` / `WorkflowRunRow.parent_run_id`
      (migration `0016_feedback_lineage.py`), set by
      `IngestionService.start_successor_run` and threaded through
      `WorkflowService.create`. Depends on T044.
- [X] T050 [US4] Terminal-run `done` branch in `FeedbackDispatcher`:
      `get_change_request(...).state` → revive via T043's resume path, or
      a linked successor. Depends on T043, T049. Makes T046 pass.
      **Judgment call, deviating from this task's literal text and from
      `contracts/change-request-resume.md`**: the successor is started
      via a new `IngestionService.start_successor_run(parent=...)`, which
      calls `WorkflowService.create` directly, instead of calling
      `maybe_start_run` unmodified. Reusing `maybe_start_run` as literally
      specified is not possible without a regression: its
      `has_run(task_ref)` dedup check treats *any* run for a `task_ref`
      (including the parent itself, which stays in the registry as
      history) as blocking a new one, and a GitHub `done` transition
      (`GitHubTaskSource.transition`) deliberately never removes the
      issue's trigger label or closes the issue — so `reconcile.py` keeps
      finding that ticket labelled and open on every poll cycle. Loosening
      `has_run` to exclude terminal runs would fix the successor path but
      would also make reconcile silently start a brand-new duplicate run
      for every already-`done`-but-still-labelled ticket on every poll
      interval, forever — a much worse regression than the one this task
      is fixing. `start_successor_run` instead funnels through
      `WorkflowService.create` (the same sole convergence point
      `maybe_start_run`/`reset.rerun` already use — see its docstring),
      skipping only the watched/dismissed/has_run filters that are
      inappropriate for an explicit, already-linked continuation. This
      keeps the "single place run creation happens" property the task
      brief asked for, without the reconcile regression. Flagged here per
      the task brief's request to report rather than silently follow a
      doc that turns out not to match the real branch's ingestion
      semantics.
- [X] T051 [US4] `escalated` branch: `driver/branch_resume.py` falls back
      to `add_worktree` (fresh, base branch off `run.base_branch`, with a
      best-effort `delete_local_branch` first so a stale local ref from
      the run's own earlier escalated attempt doesn't collide) when
      `run.pr_number` is unset (an escalated run never pushed a branch/PR
      — the signal `resume_with_feedback` branches on). Depends on T043.
      Makes T047 pass.
- [ ] T052 [US4] `publish_correction()` (decomposed branch): calls
      `TaskSource.create_subtask` once with triage-derived correction
      content, reusing feature 012's `create_subtask` port method. Depends
      on T041. Makes T048 pass. **Blocked, left unchecked** — same reason
      as T048: `create_subtask` does not exist on this branch's
      `TaskSource` protocol, and there is no `decomposed` status to route
      on. Revisit once feature 012 merges.

**Checkpoint**: All four user stories work end-to-end; the full
feedback-intake surface is live.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T053 [P] Self-loop regression test
      (`backend/tests/test_no_self_feedback_marker.py`, new): assert the
      configured trigger marker never appears in any literal comment
      template kestrel itself writes (`notifications.py`, driver comment
      strings) — the first of research.md R6's three independent guards,
      verified mechanically rather than by inspection alone.
- [X] T054 [P] Run every `quickstart.md` scenario (1-4) end-to-end against
      a fixture task source (Scenarios 1-2) and a throwaway GitHub repo
      (Scenarios 3-4); confirm each "Expect" holds. **Partially achieved,
      documented rather than fabricated**: this sandbox has no real
      GitHub repo or LLM credentials. Scenarios 1-2 were run for real —
      `backend/tests/test_feedback_quickstart_e2e.py` (new) wires the
      *real* `FeedbackPollService` -> `FeedbackIntakeService` ->
      `FeedbackDispatcher` -> `WorkflowService` chain against a real,
      tmp_path-backed `FixtureTaskSource` reading/writing the exact
      `<slug>.comments.jsonl` file format quickstart.md step 3 tells an
      operator to hand-edit — the one gap the existing per-stage tests
      (`test_feedback_intake.py`/`test_feedback_dispatch.py`/
      `test_feedback_poll.py`) left, since each of those stubs out its
      neighbours. Scenarios 3-4 need a real GitHub PR (review comments,
      merge/close lifecycle) this sandbox cannot stand up; their logical
      behaviour is covered by fakes in `test_workflow_feedback_resume.py`
      and the review-origin/terminal-run branches of
      `test_feedback_dispatch.py` — **covered by automated tests, not
      manually walked through against a real PR.**
- [X] T055 [P] Update `docs/architecture.md` (feedback-intake narrative,
      alongside the existing webhook-exception note) and add operator
      guidance (trigger-marker configuration, acknowledgment/reaction
      behaviour, revive-vs-successor behaviour) to a new or existing
      operator doc under `docs/`. Added `docs/feedback-intake.md` (new)
      plus a short cross-linking "Feedback" section in each of
      `docs/setup-github-workflow.md`/`setup-jira-workflow.md`/
      `setup-fixture-workflow.md`, matching their existing per-source
      convention. **Flagged while writing this**: `feedback_window_days`
      (T005) is a real, documented `Settings` field with a default of 14
      but is not read anywhere in the feedback pipeline (`intake.py`/
      `dispatch.py`/`poll.py`/`marker.py`) — it does nothing yet. Called
      out explicitly in `docs/feedback-intake.md` rather than documenting
      invented behaviour for it; worth a decision (wire it up, or drop it)
      before this feature is considered fully done.
- [X] T056 Run `task quality`; the repo's jscpd budget is thin (2.94% of
      the 3% gate as of the prior branch) — if a new file trips it,
      extract a shared helper rather than suppress (AGENTS.md — ask before
      overriding any limit). Result: all 8 checks clean; jscpd at 2.91%
      total (python 2.94%), unchanged from the Phase 6 baseline.
- [X] T057 Run the full backend (`pytest`) and frontend (`vitest`, to
      confirm the untouched frontend has no regression) suites once more
      end-to-end as the final regression pass. Backend: 809 passed (796
      Phase 6 baseline + 13 new T053/T054 tests). Frontend: 141 passed
      across 22 files, `git status` over `frontend/` shows zero changes —
      this feature touched no frontend file.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
  (nothing can claim/dedup/gate feedback before T002-T006 exist).
- **User Story 1 (Phase 3)**: Depends on Foundational only.
- **User Story 2 (Phase 4)**: Depends on US1's `FeedbackDispatcher`
  existing (T019) — extends its branching with the no-gate case; not a
  parallel-independent story the way 012's US1/US2 were.
- **User Story 3 (Phase 5)**: Depends on Foundational (T004 for the
  `Feedback`/port shape) and, for its dispatch wiring (T044), on US1's
  `FeedbackDispatcher` (T019) — but its own new capabilities (CodeHost
  reads, `add_worktree_existing`, `rewind_to`, triage: T027-T041) have no
  dependency on US2 and could be built by a second developer in parallel
  with Phase 4.
- **User Story 4 (Phase 6)**: Depends on US3 (T043's resume path, T041's
  triage) — the `done`/`escalated` revive paths directly reuse US3's
  branch-resume mechanics.
- **Polish (Phase 7)**: Depends on all four stories.

### Within Each Story

- Tests are written first and must fail before their corresponding
  implementation task lands (Constitution III).
- Port/protocol changes (T004, T035) before per-source implementations
  (T015-T017, T036-T037).
- `FeedbackIntakeService` (T018) before `FeedbackDispatcher` (T019) before
  either transport (T020, T021).

### Parallel Opportunities

- T004, T005, T006 in parallel (different files) once T002 lands; T003
  depends on T002.
- T008-T014 (all US1 tests) are different files — fully parallel.
- T015, T016, T017 (three source adapters) — parallel once T004 lands.
- T020, T021 (webhook vs. poll transport) — parallel once T019 lands.
- T025, T026 (the two `drain_feedback` call sites) — parallel once T024
  lands.
- T027-T032 (US3 tests) — different files, fully parallel.
- T036, T037, T038, T039, T040 — five different files, parallel once T035
  lands (T036/T037 also need T035 specifically; T038/T039/T040 don't).
- US3's own new capabilities (T027-T041) may be developed in parallel with
  Phase 4 (US2) by a second developer, per the note above.

---

## Parallel Example: User Story 1

```bash
# Once Foundational is done, launch US1's tests together:
Task: "list_comments/acknowledge contract tests for GitHub in test_github_ports.py"
Task: "list_comments/acknowledge contract tests for Jira in test_jira_client.py"
Task: "list_comments/acknowledge contract tests for fixture in test_fixture_task_source.py"
Task: "FeedbackIntakeService pipeline tests in test_feedback_intake.py"
Task: "FeedbackDispatcher gate-branch tests in test_feedback_dispatch.py"
Task: "webhook issue_comment handling test in test_github_webhook.py"
Task: "poll-transport test in test_feedback_poll.py"

# Then launch the three per-source implementations together:
Task: "GitHubTaskSource.list_comments/acknowledge in services/github.py"
Task: "JiraTaskSource.list_comments/acknowledge in services/jira.py"
Task: "FixtureTaskSource.list_comments/acknowledge in services/fixture.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1).
2. **STOP and VALIDATE**: run quickstart.md Scenario 1 against a fixture
   task; confirm a marked ticket comment redirects a parked run and an
   unmarked one changes nothing.
3. Deploy/demo if ready — SC-001 and SC-006 alone are real, shippable
   value.

### Incremental Delivery

1. Setup + Foundational → shared plumbing ready, nothing user-visible yet.
2. Add US1 → validate Scenario 1 → deploy (ticket-comment redirect live).
3. Add US2 → validate Scenario 2 → deploy (feedback never lost mid-run).
4. Add US3 → validate Scenario 3 → deploy (PR review amends the same PR).
5. Add US4 → validate Scenario 4 → deploy (post-terminal feedback finally
   reachable).
6. Polish.

### Parallel Team Strategy

Once Foundational is done: Developer A takes US1 (T008-T021), then US2
(T022-T026 — depends on US1's T019). Developer B can start US3's own new
capabilities (T027-T041) in parallel with Developer A's US2, since neither
depends on the other — but US3's dispatch wiring (T044-T045) and all of
US4 (Phase 6) wait on US1's `FeedbackDispatcher` (T019) and US3's resume
path (T043) respectively.

---

## Notes

- [P] tasks touch different files with no unresolved dependency.
- Tests are mandatory here (Constitution III), not optional — write them
  first, watch them fail, then implement.
- Commit after each task or logical group; stop at any checkpoint to
  validate a story independently.
- Every port/protocol addition (T004, T035) is additive-only — no existing
  `TaskSource`/`CodeHost` method changes signature or behaviour.
- If implementation reveals a need beyond what's in `data-model.md`'s
  "Run lineage" entity (T049) or any other under-specified shape, stop and
  reconcile with `plan.md` before proceeding, per this project's
  quality-override discipline (AGENTS.md).

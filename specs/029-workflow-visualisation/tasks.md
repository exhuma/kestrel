---

description: "Task list for the workflow visualisation rework"
---

# Tasks: Workflow visualisation rework

**Input**: Design documents from `specs/029-workflow-visualisation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md),
[research.md](./research.md), [data-model.md](./data-model.md),
[contracts/routes.md](./contracts/routes.md),
[contracts/board-api-additions.md](./contracts/board-api-additions.md),
[quickstart.md](./quickstart.md)

**Tests**: **Required, not optional.** Constitution Principle III is
NON-NEGOTIABLE: behaviour changes ship with tests, written to express intended
behaviour, and all frontend HTTP is mocked.

**Organization**: grouped by user story so each is independently implementable and
testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable — different files, no dependency on incomplete work
- **[Story]**: US1..US5, mapping to the spec's prioritised user stories

## Path Conventions

Web app: `frontend/src/`, `frontend/tests/` (mirroring `src/` one-to-one, as the
repo already does), `backend/app/`, `backend/tests/`.

---

## ⚠️ Read before starting

Six facts change how these tasks must be executed. They are not advice.

1. **`knip` treats unreferenced files as errors.** A new component that nothing
   imports yet **fails the build**. Every task that creates a component either also
   wires it into its consumer, or is explicitly paired with the task that does.
   Never leave a created-but-unimported module across a commit boundary.
2. **New files get no grandfather exemption.** 500 lines per module, 60 lines per
   JS function, cyclomatic ≤ 10, cognitive ≤ 15, nesting ≤ 4, copy-paste ≤ 3%.
   When you hit one: **split**. Never add `eslint-disable`, edit a threshold, or add
   a grandfather entry. If a limit genuinely seems wrong, **stop and ask the
   developer**.
3. **Theme colours only.** No hex, rgb, or named CSS colours anywhere
   (Principle V). Every mockup colour re-derives to `warning` / `success` / `error` /
   `primary` / `info`.
4. **Both sides of the type contract change together.** Principle I prohibits
   changing `backend/app/schemas.py` without
   `frontend/src/types/workflows.ts` in the same commit, and vice versa.
5. **There is no event SSE stream.** The per-workflow SSE carries the whole
   *snapshot*; `GET /workflows/{id}/events` is a plain REST list. "Live feed" means
   re-fetch the event list on each snapshot tick.
6. **`docs/mockups/*.png` are layout references, not an implementation model.**
   Throwaway hand-written CSS. Build from Vuetify components.

Custom CSS is permitted for **exactly three** named gaps (research R8): stage
column horizontal scroll/flex sizing, sticky column headers, and independent
per-pane scroll regions. Anything else is a signal to reach for a Vuetify
component.

---

## Phase 1: Setup

- [X] T001 Add `vue-router@^4.6.4` to `frontend/package.json` dependencies (the v4 line deliberately, not v5 — research R1) and run `npm install` in `frontend/`
- [X] T002 [P] Create the new source directories `frontend/src/router/`, `frontend/src/views/`, `frontend/src/components/board/`, `frontend/src/components/cockpit/`, `frontend/src/components/interview/`, `frontend/src/components/common/`
- [X] T003 [P] Create the mirroring test directories `frontend/tests/router/`, `frontend/tests/views/`, `frontend/tests/components/board/`, `frontend/tests/components/cockpit/`, `frontend/tests/components/interview/`
- [X] T004 [P] `git add docs/mockups/*.png` — the `.gitignore` negation exempting them from the blanket `*.png` rule is already in place, so they are untracked-but-visible and need only be added

---

## Phase 2: Backend API additions (FR-040–FR-043)

**Purpose**: expose the four facts the surfaces must show. Without these, the board
cannot nest decomposition children (the epic's headline complaint) or show titles,
and the interview cannot show a round cap.

**⚠️ Principle I**: each task below changes `backend/app/schemas.py` **and**
`frontend/src/types/workflows.ts` together. Never one without the other.

**⚠️ Boundary**: these expose facts the backend already knows. If one appears to
need a new state, transition, or write path, **stop and raise it** (FR-039).

- [X] T005 Write `backend/tests/test_board_api_additions.py` covering all four additions before implementing them: parent link `null` for a normal request and set for a decomposed child; `title` present on both DTOs and falling back to `task_label` when unrecorded; `{round, cap}` `null` for a non-capped gate and populated for a capped one; cap-exhausted `false` normally and `true` once exhausted
- [X] T006 Add the nullable decomposition parent field to `WorkflowSummaryOut` in `backend/app/schemas.py` and populate it in `backend/app/routers/board_views.py` from `ChildTaskLinkRow.parent_workflow_id` (FR-040 — persisted today, exposed nowhere, which is *why* children read as siblings)
- [X] T007 Add `title` to `WorkflowSummaryOut` and `BoardSnapshotOut` in `backend/app/schemas.py`, populated from `Workflow.title` in `board_views.py:117,137` alongside the existing `task_label=workflow.task_ref`; fall back to `task_label` when no title is recorded (FR-041)
- [X] T008 Add the nullable `{round, cap}` to the gate detail on `WorkCardSummaryOut`, sourcing the round from `backend/app/services/board/refinement_rounds.py` and the cap from `board_refinement_round_cap` (`backend/app/config.py:340`) (FR-042)
- [X] T009 Add the cap-exhausted marker to `WorkflowSummaryOut`, derived server-side (FR-043) — a fact the backend judges, **not** something the client infers by comparing counts (Principle II)
- [X] T010 Mirror all four additions in `frontend/src/types/workflows.ts` in the same commit as their backend counterparts, and extend `frontend/tests/types/workflows.test.ts` (Principle I)
- [X] T011 Amend `specs/026-autonomous-work-board/contracts/board-api.md` to record the four additions in its Workflow Collection, Board Snapshot and Card Summary sections, noting each is additive and read-only
- [X] T012 Run `cd backend && uv run pytest` and confirm no existing board test broke — every addition is additive, so any breakage means something was renamed rather than added

**Checkpoint**: `uv run pytest` and `npm run build` both pass. No visual change.

---

## Phase 3: Foundational — router infrastructure

**Purpose**: the navigation substrate every user story below depends on.

**⚠️ CRITICAL**: no user-story work can begin until this phase is complete. US4's
*guarantees* (back/forward retrace, unknown-id handling, `?run=` compatibility) are
verified in Phase 7 once there are real surfaces to navigate between; what lands
here is the scaffolding US1–US3 all need.

**Why this is foundational despite US4 being P4**: retrofitting routing after three
surfaces exist would mean rewriting every navigation call site twice.

- [X] T013 Write `frontend/tests/router/index.test.ts` asserting every named route from `contracts/routes.md` §1 resolves from a cold router: `board` → `/`, `cockpit` → `/requests/:id`, `interview` → `/requests/:id/interview`, `sessions` → `/sessions`, `not-found` catch-all
- [X] T014 Create `frontend/src/router/index.ts` with `createRouter({ history: createWebHashHistory() })` and the five named routes; lazy-load `cockpit`, `interview` and `sessions` via dynamic import, keep `board` eager (research R2 for the hash-history rationale)
- [X] T015 Register the router on the app in `frontend/src/main.ts`, replacing the one-shot `applyDeepLink` call at `frontend/src/main.ts:51` with the bootstrap sequence in `contracts/routes.md` §2
- [X] T016 Rework `frontend/src/App.vue` to a shell: replace the `view` ref (`App.vue:48`) and the `v-btn-toggle` (`App.vue:88-105`) with `<RouterView>`; keep the app bar, connectivity banner, `NotificationCenter`, `SourceHealthIndicator`, theme toggle, `IdentityBadge` and `GithubLink` untouched
- [X] T017 [P] Create `frontend/src/views/SessionsView.vue` wrapping the existing `SessionPanel.vue`, preserving its lazy load with `PanelLoading` / `PanelError` — the debug panel loses its toggle in T016 and would otherwise be unreachable (FR-047)
- [X] T018 [P] Create `frontend/src/views/NotFoundView.vue` — an explanatory message and a route back to the board; used by both the catch-all route and the unknown-request-id path (FR-030)
- [X] T019 Repoint `NotificationCenter`'s `@navigate` handler (`App.vue:122`) at `router.push({ name: 'cockpit', params: { id } })` so following a notification lands on the request itself rather than the board. Notification *generation* is out of scope
- [X] T020 Write `frontend/tests/views/AppShell.test.ts` covering the shell's routed rendering — **new coverage**: `App.vue` has no component test today, so view switching is currently untested

**Checkpoint**: `npm run test` and `npm run build` pass. The app renders the
existing board and sessions surfaces through routes, with no visual change yet.

**Implementation note (2026-09-28, task 702/#42)**: `RequestCockpitView.vue`
and `InterviewView.vue` did not exist yet when T014 needed real modules behind
the `cockpit`/`interview` routes (a dynamic `import()` to a nonexistent file
fails the build regardless of whether the route is ever visited). Both were
created here as minimal placeholders — a plain message plus a route back —
for tasks 703 (#58) and 704 (#59) to replace outright. Not a partial
implementation of either surface.

---

## Phase 4: User Story 1 — Stage board (P1) 🎯 MVP

**Goal**: one card per ingested request, grouped into six derived stage columns,
replacing the nav list as the default surface.

**Independent test**: load a fixture board containing a quarantined request, a
decomposed parent with children, a request awaiting a decision, a cap-reached
request and a terminal request. Verify column placement, the per-card phase line,
exactly one card per request, children nested inside their parent, and three
distinguishable attention treatments.

### Pure logic first (this is where the rules are tested)

- [X] T021 [P] [US1] Write `frontend/tests/lib/stages.test.ts` covering: the six stage names in order; the ten phase names in order; `phasePosition()` returning `ordinal: null` for an unrecognised phase and `isTerminal` for `done`; `attentionOf()` precedence `quarantined > cap-reached > your-move > done > none` over cards qualifying for several states; `groupByStage()` placing an **unrecognised stage** in a trailing column rather than dropping the request (FR-002 guarantees every request appears exactly once)
- [X] T022 [US1] Create `frontend/src/lib/stages.ts` implementing the above as pure functions — stage order (the six stages in FR-001's order), phase order, `phasePosition()`, `attentionOf()`, `groupByStage()`. Derive a request's column from the server's `stage` field; **never** re-derive stage from phase locally (data-model.md §2, Principle II). Derive `quarantined` from `state_counts` and `cap-reached` from the FR-043 marker
- [X] T023 [US1] Extend `frontend/src/composables/useBoard.ts` to request `include_completed=true` on both `refresh()` (`useBoard.ts:32-42`) and the SSE list stream — the listing drops terminal workflows by default (`backend/app/routers/board.py:228-237`), so without this the Done column is permanently empty (FR-044)
- [X] T024 [P] [US1] Extend `frontend/tests/composables/useBoard.test.ts` to assert the flag is sent and terminal workflows arrive

### Components (each paired with its consumer, per knip)

- [X] T025 [P] [US1] Create `frontend/src/components/common/PhaseProgress.vue` using `v-progress-linear` with `chunk-count` + `variant="split"` (verified present — research R4), props for count and position, theme colour only
- [X] T026 [P] [US1] Write `frontend/tests/components/common/PhaseProgress.test.ts` asserting segment count and that a `null` ordinal renders no position bar
- [X] T027 [US1] Create `frontend/src/components/board/RequestSubItems.vue` rendering a request's nested work as a `v-list` — **both** the request's own cards (interview personas, implementation items) and its decomposition children, which are separate workflows identified via the FR-040 parent link (FR-002)
- [X] T028 [US1] Create `frontend/src/components/board/RequestCard.vue` — `v-card` / `v-card-item` showing source ref **and** human title from FR-041 (never a bare workflow id, FR-003), the exact phase in words plus its position in the ten-phase sequence (FR-004), action `v-chip`s, and the attention treatment from `attentionOf()` (FR-005); composes `RequestSubItems`
- [X] T029 [US1] Write `frontend/tests/components/board/RequestCard.test.ts` covering all five attention treatments rendering distinguishably, ref-and-title display with the title falling back to the ref when absent, the phase line text, and children rendering nested
- [X] T030 [US1] Write `frontend/tests/components/board/RequestSubItems.test.ts` asserting a decomposition child nests under its parent, and that a child whose parent is **absent from the listing** falls back to top-level rather than vanishing (FR-002 guarantees exactly once, not at most once)
- [X] T031 [US1] Create `frontend/src/components/board/StageColumn.vue` — `v-sheet` + `v-list` with a sticky header and a count; composes `RequestCard`. **Named custom-CSS gap**: sticky header, plus the column's bounded scroll region
- [X] T032 [US1] Create `frontend/src/views/StageBoardView.vue` — the column track, `v-empty-state` for an empty board (FR-008), the error `v-alert`, and the `refresh()` / `startList()` / `stop()` lifecycle currently in `WorkBoard.vue:26-33`. **Named custom-CSS gap**: horizontal scroll and flex sizing of the column track
- [X] T033 [US1] Point the `board` route at `StageBoardView.vue` in `frontend/src/router/index.ts`, replacing `WorkBoard.vue` as the default surface (FR-009). The nav list is retired at this point
- [X] T034 [US1] Make each card open its request's cockpit route on click and on `Enter`
- [X] T035 [US1] Write `frontend/tests/views/StageBoardView.test.ts` covering the six known columns in FR-001's order, the empty state, one-card-per-request across the quarantine and decomposition fixtures, and terminal requests landing in Done rather than being dropped
- [X] T036 [US1] Write `frontend/tests/views/StageBoardView.a11y.test.ts` asserting every card is keyboard-reachable and openable, that every pointer-available intervention has a keyboard equivalent (FR-007, spec 026 FR-031), and that **no drag affordance exists anywhere** on the board (FR-006, spec 026 **FR-032**)

**Checkpoint**: the board is the default surface and independently demonstrable.
`task quality` passes. The graph and `WorkCardDetail` still exist — removal is
Phase 8.

**Implementation notes (2026-09-28, task 702/#42)**:

- `WorkBoard.vue`, `WorkflowGraph.vue`, `lib/boardGraph.ts` and
  `WorkCardDetail.vue` were **not** deleted or repointed — the `board` route
  now points at `StageBoardView.vue` and nothing else references them, but
  `knip.json`'s `entry` includes `tests/**/*.test.ts`, and each still has its
  own passing test, so they stay knip-reachable (and `task quality` green)
  without being wired into the live app. This matches task 705 (#60,
  "Only after tasks 06 and 07 have landed — this removes the only structural
  view that currently exists") expecting the graph to still exist after this
  task lands. Do not delete them before 705.
- T027's "request's own cards" half of `RequestSubItems.vue` renders a
  per-`CardState` count (`state_counts`), not individually named/titled
  cards — the board **listing** (`WorkflowSummaryOut`) never carried
  individual card rows, only aggregates; fetching every workflow's full
  snapshot just to nest named cards on the board would be an N+1 fetch this
  task list never asked for. Decomposition children (the other half) *are*
  individually named, since each is its own row in the same listing.
  Individually named own-cards are the cockpit's job (task 703), backed by
  the snapshot it already loads for one request.

---

## Phase 5: User Story 2 — Request cockpit (P2)

**Goal**: for one request, say **where** it is, **why** it got there, **what** it
produced, and **what it wants** from the operator.

**Independent test**: open a mid-pipeline fixture request. The spine marks the
current phase and distinguishes gates from work phases; the feed is chronological
with a persona per event; the rail shows the durable artifact set with states; the
pending decision is stated exactly once, prominently.

### ⚠️ T037 is a gate, not a task — do it first

- [X] T037 [US2] **Legibility gate (research R3)**: render ten `v-timeline direction="horizontal"` items with the real phase labels (including "CAB-1 - strategic fit" and "Technical analysis") at 1280 px width and judge legibility. Try `density="compact"`, `align="start"`, then abbreviating gate labels with a tooltip carrying the full name. **If it still does not read cleanly, switch the spine to a vertical labelled list** for T041. Do **not** hand-write horizontal stepper CSS — both #58 and FR-036 forbid it. Record the outcome as an addendum in `research.md`

### Pure logic and data access

- [X] T038 [P] [US2] Write `frontend/tests/lib/personas.test.ts` covering `BoardEvent` → `PersonaLabel` for all three cases, **especially `specialist: null` resolving to the neutral `{ kind: 'system' }`** and never to a guessed or blank name (FR-013); plus tone and summary mapping
- [X] T039 [US2] Create `frontend/src/lib/personas.ts` as pure functions returning the tagged union from data-model.md §2. Reuse the tone-map idiom from `SessionPanel.vue:325-368` rather than inventing a second one. Add a comment recording that `specialist` is a **read-time derivation from the card's eligible role, not a recorded actor** (`backend/app/schemas.py:239-244`)
- [X] T040 [US2] Create `frontend/src/composables/useBoardEvents.ts` — fetch `GET /api/board/workflows/{id}/events` and **re-fetch on each snapshot tick from the existing board SSE**. There is no event stream to subscribe to: the per-workflow SSE carries the whole snapshot (`backend/app/routers/board.py:337-371`). Module-level singleton keyed per workflow, no Pinia. `BoardEvent` already exists at `frontend/src/types/workflows.ts:95-101` and this is its first consumer
- [X] T041 [P] [US2] Write `frontend/tests/composables/useBoardEvents.test.ts` with all HTTP mocked, covering initial fetch, re-fetch on snapshot tick, deduplication of already-seen events, and teardown

### Components

- [X] T042 [US2] Create `frontend/src/components/cockpit/PhaseSpine.vue`, the structural view of a request in place of the dependency graph (FR-019), per the T037 outcome — ten labelled phases, gate phases with a distinct `v-timeline-item` icon, current phase with a theme `dot-color` (FR-011)
- [X] T043 [P] [US2] Write `frontend/tests/components/cockpit/PhaseSpine.test.ts` covering current-phase highlighting (for "PRD sign-off": **five** phases passed, **four** not yet reached), gate-vs-work distinction, and an unrecognised phase rendering its label verbatim with no position marker
- [X] T044 [US2] Create `frontend/src/components/cockpit/FeedEntry.vue` — one row with `v-avatar` per persona, attribution, tone and summary; renders the neutral case without an empty name
- [X] T045 [US2] Create `frontend/src/components/cockpit/NarrativeFeed.vue` — `v-timeline density="compact" side="end"`, chronological and persona-attributed, oldest-first (FR-012), composing `FeedEntry`. Auto-scroll on new events **but suppressed while the operator has scrolled back** (FR-018). **Named custom-CSS gap**: bounded independent scroll region
- [X] T046 [US2] Write `frontend/tests/components/cockpit/NarrativeFeed.test.ts` covering chronological order, live append without manual refresh, that a scrolled-back operator is not yanked to the bottom, and that a large event history does not degrade rendering
- [X] T047 [P] [US2] Create `frontend/src/components/cockpit/ArtifactDialog.vue` — `v-dialog` rendering artifact content as **text, never markup**, and surfacing `trust` so `agent_output` cannot be mistaken for `operator_approved` (FR-015). Reuse the fetch at `WorkCardDetail.vue:22`
- [X] T048 [P] [US2] Write `frontend/tests/components/cockpit/ArtifactDialog.test.ts` asserting markup in content renders as literal text, and that trust is displayed
- [X] T049 [US2] Create `frontend/src/components/cockpit/ArtifactRail.vue` — `v-list` of the full durable set in pipeline order (original request, understanding check, CAB-1 decision, interview rounds, PRD, technical analysis, executive summary, pull request), each with `prepend-icon`, an append `v-chip` state, and `available: false` for those not yet produced (FR-014, data-model.md §2); opens `ArtifactDialog`
- [X] T050 [US2] Write `frontend/tests/components/cockpit/ArtifactRail.test.ts` asserting the full durable set renders in pipeline order, each with its state, and that unproduced artifacts appear as unavailable rather than being omitted (FR-014)
- [X] T051 [US2] Create `frontend/src/components/cockpit/ActionBanner.vue` — a `v-alert` with buttons in the `append` slot stating the single pending ask, rendering **nothing at all** when nothing is pending (FR-016). Port the gate-decision branching from `WorkCardDetail.vue:76-93`, including `requested_decision === 'answer'` and `'approve_prd'`
- [X] T052 [US2] Replace any `window.confirm()` in the ported paths with `v-dialog` (FR-038 — there is no `v-dialog` anywhere in the app today)
- [X] T053 [US2] Write `frontend/tests/components/cockpit/ActionBanner.test.ts` covering: exactly one banner when a gate is pending, no element at all when nothing is pending, and a 409 stale `expected_revision` surfacing as a human "this moved on" message rather than a generic failure (`useBoard.ts:112-131`)
- [X] T054 [US2] Create `frontend/src/views/RequestCockpitView.vue` composing banner, spine, feed and rail; loads the snapshot via `useBoard().select(id)`; routes an unknown id to `NotFoundView` with a way back to the board (FR-030). **Named custom-CSS gap**: independent per-pane scroll regions
- [X] T055 [US2] Route every answer-shaped interaction from the cockpit to the interview route rather than handling it inline — the feed stays read-only (FR-017)
- [X] T056 [US2] Write `frontend/tests/views/RequestCockpitView.test.ts` covering the four regions rendering, scoping to exactly one request (FR-010), a load failure stating itself plainly with a route back, the unknown-id guard, and keyboard operability of the banner's actions (SC-010)

**Checkpoint**: a request's cockpit is independently demonstrable. `task quality`
passes.

**Implementation notes (2026-09-28, task 703/#58)**:

- **T037 cleared the gate: the horizontal spine stands.** Measured against a
  throwaway probe rendering all ten real labels at fixed widths; the outcome
  and the numbers are recorded as an addendum under research R3. The settings
  are `density="compact"` + `align="start"`, which is what makes ten labels fit
  on one line at 1248 px; below ~1100 px they wrap rather than truncate. Neither
  pre-agreed mitigation (abbreviated gate labels, vertical `v-list` fallback)
  was needed — both were rendered and rejected on the evidence.
- **Two pure modules were extracted beyond the task list**, because the banner
  and the rail would otherwise have carried their derivation inline and blown
  the complexity and function-length limits: `frontend/src/lib/artifacts.ts`
  (the durable set and its per-entry state) and `frontend/src/lib/asks.ts`
  (what the request wants from the operator). Both are unit-tested directly,
  which is also where the interesting rules now live.
- **Rejection feedback is taken in a `v-dialog`, not on the interview route.**
  US2 scenario 7 calls both interview answers and rejection feedback
  "answer-shaped", but only interview answers have a dedicated surface; T052
  independently mandates a `v-dialog` for the ported confirm paths. So an
  `answer` gate routes away to `interview` (T055/T075) and a `prd_gate`
  rejection opens a dialog that refuses to submit without feedback. Nothing is
  typed into the feed either way, which is what FR-017 protects.
- **Quarantine resolution was absorbed into `ActionBanner` too**, though no task
  asked for it. T087 only names the gate-decision logic and the artifact fetch
  as things to absorb before deleting `WorkCardDetail.vue`, but release/discard
  lives there as well — without this, Phase 8 would have quietly dropped an
  operator capability, against its own checkpoint. Quarantine outranks every
  gate in `pendingAsk`.
- **FR-039 finding — two rail entries have no backend producer.** `Original
  request` lives on `Workflow.task_body`, which the board snapshot does not
  carry, and `Executive summary` has no card kind at all until GitHub #50–#52
  land. Both render as `Not yet produced` rather than being hidden, which is
  what an *expected* set is for. **Surfacing the original request would need a
  fifth DTO addition**, so it was not made here: FR-039 reserves that for the
  developer.

  **Raised and now decided (2026-09-28).** The developer wants the request body
  readable in the cockpit, and ruled the four-field count a guardrail against
  scope creep rather than a fixed number. **The work is deferred to task 707
  (GitHub #50–#52)**, which already opens the backend for the rail's *other*
  empty slot — so both gaps close together, and **this feature's own four-field
  boundary still holds**: the fifth field lands in 707's scope, not in 029's
  diff, so T095 stands unamended. Decisions for 707 to implement:

  - `task_body` goes on `BoardSnapshotOut` **only**, never on
    `WorkflowSummaryOut` — full issue bodies on every board row would bloat the
    listing for nothing.
  - **No trust chip on this one entry.** The chip exists to stop `agent_output`
    being mistaken for `operator_approved` (FR-015); the request body is
    neither, and a third trust vocabulary would blunt that distinction rather
    than sharpen it.
  - **Show a freshness note instead**: `task_body` is screened once at intake
    and frozen, so a later edit to the source ticket is never reflected. Say so
    where it is read.
  - `ArtifactDialog` opens artifacts *by id* via the content endpoint. The
    request body has no artifact id, so it needs a direct-content path — either
    a second mode on that dialog or a sibling component.
- Eight icon aliases were added to `frontend/src/plugins/icons.ts` for the rail.
  Its test's hard-coded alias list was hoisted to a module constant — adding
  icons had pushed the `describe` block past the 60-line function limit, and
  splitting was the sanctioned fix rather than an exemption.
- `frontend/tests/support/board.ts` gained `workCardSummary`, `boardSnapshot`
  and `boardEvent` builders, and its `testRouter` gained the `interview` and
  `not-found` routes the cockpit links to.

---

## Phase 6: User Story 3 — Interview workspace (P3)

**Goal**: answer an interview without being forced to invent an answer, and without
losing work.

**⚠️ Recover, do not rewrite** (research R5) — but **recover, then split**
(research R9/R10). Restore under the `interview*` names, not `questionnaire*`: the
ESLint grandfather list still names `lib/questionnaire.ts` (`complexity: 'off'`,
`frontend/eslint.config.js:82`) and `QuestionnaireForm.test.ts`
(`max-lines-per-function: 'off'`, `:87`), so reusing those filenames would give
**new** files a stale exemption. Renaming removes the exemption but **not the
violation it was covering** — so both files must be split to satisfy the limits.

**Independent test**: open a fixture interview with two personas across a capped
multi-round sequence. Verify per-persona grouping, the round indicator stating
current round and cap, drafts surviving navigation away and back, both escape
hatches per question, and submit returning to the cockpit.

### Recover the prior art

- [X] T057 [US3] Restore `frontend/src/lib/debounce.ts` verbatim from `3fc281c^` (14 lines, needs no adaptation)
- [X] T058 [US3] Restore `3fc281c^:frontend/src/types/questionnaire.ts` (86 lines) as `frontend/src/types/interview.ts`; re-point the answer model at the current `WorkCardGate` / `BoardInterventionRequest` shapes and the FR-042 `{round, cap}`. **Note**: not mentioned in #59, but recovering the lib without it means re-deriving the types
- [X] T059 [US3] Restore `3fc281c^:frontend/src/lib/questionnaire.ts` (244 lines) as `frontend/src/lib/interview.ts` — `groupByProfile` (→ grouping by persona) and the answer model, adapted to current shapes. **Then split it**: that file was grandfathered for `complexity`, so as-restored it exceeds cyclomatic 10 and now has no exemption. Extract the answer-model helpers into a second module rather than suppressing
- [X] T060 [US3] Add question-set parsing to `frontend/src/lib/interview.ts` — the questions are **not** an API resource; they live as text inside the interview/refinement card's artifact (`backend/app/services/board/refinement.py:38-88`), reachable only via `GET /api/board/artifacts/{id}/content`. Pure function, tested against real artifact samples (FR-045)
- [X] T061 [US3] Restore `3fc281c^:frontend/tests/lib/questionnaire.test.ts` (237 lines) as `frontend/tests/lib/interview.test.ts`, adapting to the new names and shapes; extend to cover all four answer states from data-model.md §2, that `unknown` and `not-relevant` are **never serialised as an empty answer** (FR-023), that whitespace-only text is `unanswered`, `allRequiredAnswered` gating (FR-026), and question-set parsing including an unparseable artifact
- [X] T062 [US3] Extract the draft, debounced-commit and **round-advance answer reconciliation** logic from `3fc281c^:frontend/src/components/QuestionnaireForm.vue` (458 lines) into `frontend/src/composables/useInterviewDraft.ts`, as a **module-level singleton keyed per workflow and round** — component state would not survive leaving the route, which FR-022 requires. Reconciliation is keyed on the round; port it rather than reinventing it (FR-022, FR-025)
- [X] T063 [US3] Write `frontend/tests/composables/useInterviewDraft.test.ts`, seeded from `3fc281c^:frontend/tests/components/QuestionnaireForm.test.ts` (381 lines) but **split into several test functions** — the source file was grandfathered for `max-lines-per-function` and has no exemption under its new name. Cover draft survival across unmount, debounced commit, idle/dirty/saving/saved transitions, and **round advance with previous-round answers present reconciling rather than discarding or misattributing**

### Components

- [X] T064 [P] [US3] Create `frontend/src/components/interview/RoundIndicator.vue` — `v-chip` plus `PhaseProgress` with `chunk-count="<cap>"`, reading `{round, cap}` from FR-042; derives the "final round before assumptions are recorded in the PRD" wording from `round === cap` so the two cannot disagree (FR-024). A `null` round/cap degrades to a single round (FR-027). Written fresh, **not** recovered from `RoundChips.vue` — research R5 explains why
- [X] T065 [P] [US3] Write `frontend/tests/components/interview/RoundIndicator.test.ts` covering round 3 of 3 stating finality, mid-sequence not stating it, and the `null` single-round degraded case
- [X] T066 [US3] Create `frontend/src/components/interview/QuestionField.vue` — `v-textarea` plus both escape hatches: "I don't know — let the PRD state an assumption" and "not relevant" (FR-023). Do **not** re-specify outlined/compact; the global `defaults` at `frontend/src/main.ts:28-46` already set them for `VTextarea` (`:36-41`)
- [X] T067 [US3] Write `frontend/tests/components/interview/QuestionField.test.ts` asserting each of the four answer states is reachable and distinguishable, and that neither escape hatch produces an empty answer
- [X] T068 [US3] Create `frontend/src/components/interview/PersonaQuestionGroup.vue` — a `v-card` per persona (`v-expansion-panels` if they should collapse), composing `QuestionField` (FR-021)
- [X] T069 [US3] Create `frontend/src/views/InterviewView.vue` — `v-form` shell composing `RoundIndicator` and `PersonaQuestionGroup`; loads the question set via T060 and **states plainly when the artifact cannot be read** rather than showing an empty interview (FR-045); `v-snackbar` draft feedback clearly distinguishable from submission (FR-022); refuses submit while a required question is neither answered nor waived, identifying the outstanding questions (FR-026)
- [X] T070 [US3] Implement the submit path: record every answer against its question through the existing `resolve_gate` intervention, carrying `expected_revision` (FR-046). **Define and document the serialisation** — the API offers a single free-text `answer` field, so an "I don't know" and a "not relevant" must arrive distinguishable, not both as empty text. Record the chosen format in `data-model.md`
- [X] T071 [US3] Surface a 409 stale-revision response from submit as a human "this moved on" message, matching the banner's treatment (FR-046, spec's "stale decision" and "concurrent surfaces" edge cases)
- [X] T072 [US3] On successful submit, navigate to the `cockpit` named route with the same `id` — **by name, not `router.back()`**, because the operator may have arrived from a bookmark or notification with nothing behind them (FR-020, `contracts/routes.md` §1)
- [X] T073 [US3] Add the `interview` route guard: a request with no open interview redirects to its cockpit, which states what it *is* waiting on
- [X] T074 [US3] Write `frontend/tests/views/InterviewView.test.ts` covering per-persona grouping, refused submit with outstanding required questions, successful submit navigating to the cockpit by name **and the submitted answers being visible there** (US3 scenario 8), draft-vs-submitted feedback being distinguishable, the unreadable-artifact message, the 409 path, the no-open-interview redirect, and keyboard operability throughout (SC-010)
- [X] T075 [US3] Wire the cockpit's `ActionBanner` CTA for interview-shaped gates to the `interview` route (closes FR-017 end to end)

**Checkpoint**: an interview round can be completed and submitted entirely from the
UI — impossible before this feature (SC-005). `task quality` passes.

---

## Phase 7: User Story 4 — Addressability guarantees (P4)

**Goal**: verify and complete the navigation guarantees now that there are real
surfaces to move between. The scaffolding landed in Phase 3; the *guarantees* are
only testable here.

- [ ] T076 [US4] Implement the legacy `?run=<id>` redirect per `contracts/routes.md` §2 — `runIdFromSearch(window.location.search)` resolving to the `cockpit` route via `router.replace` (a **replace**, so back never lands on the redirect). Keep `lib/deeplink.ts`'s existing signature so `frontend/tests/lib/deeplink.test.ts` stays valid; only the injected `select` callback changes to navigate
- [ ] T077 [US4] Write `frontend/tests/router/legacyDeepLink.test.ts` covering `/?run=<id>` resolving to that request's cockpit (FR-031) and back **not** returning to the redirect
- [ ] T078 [P] [US4] Write `frontend/tests/router/history.test.ts` walking board → cockpit → interview and asserting back twice yields cockpit then board, **and forward twice retraces it again** (FR-029)
- [ ] T079 [P] [US4] Write `frontend/tests/router/coldStart.test.ts` asserting each address renders its surface directly in a fresh router, without the board rendering first (FR-028)
- [ ] T080 [P] [US4] Write `frontend/tests/views/NotFoundView.test.ts` asserting an address naming a nonexistent request, and an unmatched path, both produce the explanatory surface with a route back to the board — not a blank page and not an error trace (FR-030)
- [ ] T081 [P] [US4] Assert no surface address carries anything beyond an opaque workflow id (FR-032), and that `cockpit`, `interview` and `sessions` are lazily loaded while `board` is eager
- [ ] T082 [P] [US4] Assert the `sessions` route reaches the debug panel, which lost its toggle in T016 (FR-047)

**Checkpoint**: every surface is addressable, back and forward retrace, and old
links still work.

---

## Phase 8: User Story 5 — Retirement (P5)

**Goal**: remove the graph and everything it propped up. **Nothing here may start
until Phases 4 and 5 are complete and green** — the graph is the only structural
view that exists today.

- [ ] T083 [US5] Delete `frontend/src/components/WorkflowGraph.vue` (124 lines) and `frontend/src/lib/boardGraph.ts` (92 lines)
- [ ] T084 [US5] Delete `frontend/tests/components/WorkflowGraph.test.ts` and `frontend/tests/lib/boardGraph.test.ts`
- [ ] T085 [US5] Remove `@vue-flow/core` from `frontend/package.json` and run `npm install` to update the lockfile (Principle IV — a graph library that renders a straight line is not a justified dependency)
- [ ] T086 [US5] Delete `frontend/src/components/WorkBoard.vue` (166 lines) and its list/graph `v-btn-toggle`, plus `frontend/tests/components/WorkBoard.test.ts` (FR-034)
- [ ] T087 [US5] Delete `frontend/src/components/WorkCardDetail.vue` (267 lines) and its test, **only after** confirming `ActionBanner.vue` has taken over its gate-decision logic (`:76-93`) and `ArtifactDialog.vue` its artifact fetch (`:22`) — superseded by absorption, not simply dropped
- [ ] T088 [US5] Fix the false comment at `backend/app/main.py:249-251`: `StaticFiles(html=True)` serves `404.html` then raises 404 — it does **not** fall back to `index.html` for deep paths (verified in `starlette/staticfiles.py:134-152`). Comment-only change; state that addresses are hash-based so no SPA fallback is needed
- [ ] T089 [US5] Run `cd frontend && npm run knip` and confirm no new findings (FR-035)
- [ ] T090 [US5] Run `cd frontend && npm run depcruise` and confirm the views → components → composables → lib → types direction holds with no cycles
- [ ] T091 [US5] Grep `frontend/src` and `frontend/tests` for `vue-flow`, `WorkflowGraph`, `boardGraph`, `WorkBoard` and `WorkCardDetail` — expect no hits

**Checkpoint**: one dependency in, one out. No operator-visible capability lost.

---

## Phase 9: Polish & cross-cutting

- [ ] T092 [P] Verify no hex, rgb, or named CSS colour appears in any file added by this feature (Principle V, FR-037) — grep the new directories
- [ ] T093 [P] Verify the custom CSS added across the feature covers **only** the three gaps named in research R8, and that each site carries a comment naming its gap (FR-036)
- [ ] T094 [P] Confirm no added file exceeds 500 lines and no added function exceeds 60 lines, and that **no** suppression, threshold edit, or grandfather entry was introduced anywhere (FR-035, SC-013)
- [ ] T095 Verify FR-039 held: the backend diff contains only the four additive fields, their tests, the contract amendment and the T088 comment — no new state, transition, write path or endpoint, and no consumer of the phase projection outside read paths
- [ ] T096 [P] Verify SC-011 at 1280 px: all six stage columns reachable, and each card's source ref, phase line and attention treatment readable without horizontal truncation, including when one column is full
- [ ] T097 [P] Verify the connectivity-loss path: a live surface that loses its stream says so rather than appearing merely quiet, and recovers when connectivity returns (spec edge case)
- [ ] T098 Update `docs/architecture.md` to describe the three surfaces, the routed navigation and the four DTO additions, replacing any description of the nav list and graph view (constitution: behavioural changes update the relevant docs)
- [ ] T099 Walk `quickstart.md` end to end against a seeded fixture board and correct anything that does not match what was built
- [ ] T100 Run the full gate: `task quality`
- [ ] T101 Run the pre-push checks `task quality` does not cover: `cd frontend && npm run format:check && npm run build && npm run test`, then `cd backend && uv run pytest`
- [ ] T102 Close out GitHub sub-issues #57, #58, #59, #60 and epic #40, recording what landed, the three developer decisions (routing library, hash history, the four DTO additions), and that FR-033 supersedes spec 026 FR-030

---

## Dependencies

```
Phase 1 (Setup)
   ↓
Phase 2 (Backend API additions) ─── blocks US1's nesting/titles and US3's round cap
   ↓
Phase 3 (Foundational: router) ─── blocks everything
   ↓
Phase 4 (US1 Stage board, P1) ◄── MVP
   ↓
Phase 5 (US2 Cockpit, P2) ─── needs a board to open from
   ↓
Phase 6 (US3 Interview, P3) ─── needs the cockpit's CTA to arrive from
   ↓
Phase 7 (US4 Addressability, P4) ─── needs several surfaces to navigate between
   ↓
Phase 8 (US5 Retirement, P5) ─── MUST be last; needs US1 + US2 green
   ↓
Phase 9 (Polish)
```

**Story independence**: US1 is fully independent once Phases 2–3 land. US2 depends
on US1 only for an entry point (a cockpit address can be visited directly, so it is
testable alone). US3 depends on US2 for its CTA. US4 verifies guarantees across
US1–US3. US5 is a hard-ordered cleanup.

**Within-phase parallelism**: tasks marked `[P]` touch different files and can run
concurrently. The largest clusters are T021+T024+T025+T026 (US1 logic and the
shared bar), T038+T041+T043+T047+T048 (US2 tests), T064+T065 (US3 round indicator),
T078–T082 (US4 router tests), and T092–T094+T096+T097 (polish).

**Sequential by necessity**: T005 before T006–T009 (test first). T010 in the *same
commit* as T006–T009 (Principle I). T022 after T021 (test first). T037 before T042 —
the legibility gate decides what the spine *is*. T059 before T061; T062 before
T063. T087 after T051 and T047 — absorption before deletion. All of Phase 8 after
Phases 4–5.

---

## Implementation strategy

**MVP = Phases 1 + 2 + 3 + 4.** That delivers the stage board: one card per
request, six ordered columns, decomposition children nested inside their parent,
honest phase display, keyboard-operable. It alone fixes the epic's core complaint
("the left nav shows one request as several") and is demonstrable with the graph and
detail pane still in place.

**Then incrementally**: Phase 5 makes a request legible; Phase 6 makes it operable —
the first time an interview can be answered from the UI at all; Phase 7 makes every
surface addressable; Phase 8 collects the dependency saving.

**Suggested commit boundaries**: one per phase checkpoint, each with `task quality`
green. Phase 2 must be a single commit spanning backend and frontend types
(Principle I). Phase 8 is a natural single commit ("remove the graph view and
@vue-flow/core"); keep the `backend/app/main.py` comment fix (T088) in it — same
finding.

**One open item** (plan.md § Open items) wants the developer's word, though it
blocks nothing:

- **Hash vs clean URLs** — hash history was chosen so the bundled image and the dev
  server behave identically without a backend catch-all. Decide before Phase 3
  lands. The other former open item (stale grandfather entries) is resolved: the
  `interview*` naming sidesteps it, and T059/T063 split the recovered files so they
  meet the limits without needing any exemption.

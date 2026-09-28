# Phase 0 Research: Workflow visualisation rework

**Feature**: `specs/029-workflow-visualisation` | **Date**: 2026-09-28

All unknowns below were resolved by inspecting the installed dependencies, the
npm registry, and the repository itself — not from recollection. Version numbers
and file paths are as observed on 2026-09-28.

---

## R1. Routing library: which, and which major line

**Decision**: add `vue-router@^4.6.4` as a production dependency.

**Rationale**: The `vue-router` 5.x line (latest 5.3.1) declares four extra peer
dependencies — `vite`, `pinia`, `@pinia/colada`, `@vue/compiler-sfc`. All four
are marked `optional: true`, so v5 would not *force* Pinia into the tree, but
those peers exist to serve v5's data-loader feature set, which this feature has
no use for. The v4 line peers on `vue: ^3.5.0` alone (project has `vue ^3.5.39`),
and ships roughly half the unpacked weight — 663 KB against 1.25 MB.

Two project constraints make v4 the correct call:

- The frontend convention is explicitly **no Pinia/Vuex** — shared state lives in
  module-level singleton composables (`module-vue-vuetify`, and the existing
  `composables/useBoard.ts` follows it). Adopting a router whose optional
  ecosystem pulls toward Pinia invites drift against that.
- Constitution Principle IV: dependencies are added only when a present need
  justifies them. The present need is address-per-surface and history
  navigation. v4 covers it completely; v5's surplus is YAGNI.

**Alternatives considered**:

| Option | Disposition |
| --- | --- |
| `vue-router@5.3.1` | Rejected — surplus feature surface and Pinia-adjacent peers for no present need. |
| Extend `lib/deeplink.ts` with `?view=` | Rejected by the developer on 2026-09-28. Would mean hand-writing URL writes, history entries, `popstate` handling and address parsing — reimplementing a router, less well, and owning its edge cases (double-push dedup, scroll restoration) in our own test suite. |
| Keep the plain `ref` with no URL state | Rejected — cannot satisfy FR-028/FR-029/FR-031, and leaves the interview unable to return to its cockpit by navigation. |

**Principle IV justification** (carried into the plan's Complexity Tracking
table): one dependency is **removed** in the same feature (`@vue-flow/core`,
which renders a straight line — see R6), so the frontend's production dependency
count does not grow. `@mdi/js`, `vue`, `vuetify`, `vue-router` is the resulting
set.

---

## R2. History mode: hash, not HTML5 — and a wrong comment to fix

**Decision**: use `createWebHashHistory()`. Addresses are
`/#/`, `/#/requests/<id>`, `/#/requests/<id>/interview`.

**Rationale**: This is the finding that forced the decision. The bundled image
serves the SPA via `StaticFiles(directory=static_dir, html=True)`
(`backend/app/main.py:256-258`), and the comment above it
(`backend/app/main.py:250-251`) claims `html=True` "serves index.html for unknown
paths, giving the SPA its client-side routing".

**That comment is false.** Reading the installed Starlette
(`backend/.venv/lib/python3.12/site-packages/starlette/staticfiles.py:134-152`):
`html=True` serves `index.html` only for *directory* requests; for any other
unmatched path it looks for `404.html` and, absent that, raises
`HTTPException(status_code=404)`. There is no `404.html` in the build output. The
application gets away with this today only because it has no path-based routes at
all — every address is `/` plus a query string.

So HTML5 history mode would produce a dev/prod split: Vite's dev server does
history fallback by default, so `/requests/abc` would reload fine under `npm run
dev` and **404 on reload in the bundled image**. The constitution requires both
run modes to keep working ("Run modes": bundled image and run-from-source MUST
both remain working), and a failure that only appears in the packaged artifact is
the worst shape for it to take.

Hash history removes the question entirely: the server never sees the route, so
both run modes behave identically with no backend change. That also preserves
this feature's stated boundary — frontend-only, no endpoint added, no response
shape changed.

**Alternatives considered**:

| Option | Disposition |
| --- | --- |
| `createWebHistory()` + a backend SPA catch-all route | Rejected. Buys cosmetically cleaner URLs at the cost of a backend route, its test, and a new prod-only failure mode if the catch-all's path exclusions ever drift from the API prefixes. For a single-user, loopback-bound local tool with no SEO or link-sharing surface, the URL aesthetics are worth less than the asymmetry is worth avoiding. |
| `createWebHistory()` with a committed `404.html` copy of `index.html` | Rejected — makes every deep link resolve with HTTP 404, which breaks caching and monitoring semantics to save a route. |

**Follow-on fix (in scope, no behaviour change)**: correct the misleading comment
at `backend/app/main.py:249-251` so the next reader does not rely on a fallback
that is not there. This is a comment-only edit.

---

## R3. `v-timeline direction="horizontal"` for the ten-phase spine

**Decision**: build the cockpit spine on `v-timeline`, with a
**mandated pre-build legibility check** and a defined fallback.

**Verified available**: Vuetify 4.1.2 is installed.
`node_modules/vuetify/lib/components/VTimeline/VTimeline.d.ts` declares
`TimelineDirection = 'vertical' | 'horizontal'`, plus `side`, `align`
(`'center' | 'start'`), `justify` (`'auto' | 'center'`), `density`,
`truncateLine` (`'start' | 'end' | 'both'`), `lineThickness`, `lineInset` and
`lineColor`. So the component supports the shape #58 asks for.

**What is not verified**: whether **ten** labelled items — with labels as long as
"CAB-1 - strategic fit" and "Technical analysis" — render legibly at a laptop
viewport. This cannot be settled by reading type definitions, and #58 explicitly
requires it be checked before building. It is therefore a task-level gate, not an
assumption.

**Fallback, pre-agreed so nobody improvises it under pressure**: if ten labelled
horizontal items do not read cleanly, switch the spine to a **vertical labelled
list** (`v-list` or `v-timeline direction="vertical"`). The fallback is
explicitly **not** hand-rolled horizontal-stepper CSS — that route is how a
Vuetify-first surface becomes a bespoke one, and both #58 and FR-036 forbid it.
Useful mitigations to try before falling back, in order: `density="compact"`,
`align="start"`, abbreviating the two gate labels in the spine while keeping the
full name in a tooltip.

### Addendum (2026-09-28, T037): gate cleared — horizontal spine confirmed

The check was run against a throwaway probe page rendering all ten real phase
labels through Vuetify's own components at fixed widths, screenshotted at a
1280 px viewport. Four treatments were compared.

**Outcome: the horizontal spine stands. No fallback, no abbreviation.**

The settings are `direction="horizontal"` **plus `density="compact"` and
`align="start"`**, with `size="x-small"` dots:

| Available width | Result |
| --- | --- |
| 1248 px (a 1280 px viewport less page padding) | all ten labels on **one line**, no wrap, no truncation |
| 1150 px | all ten still on one line |
| 1024 px | the three longest labels wrap to two lines; all text still fully visible |
| 900 px | more wrapping, up to three lines; still fully legible, still nothing truncated |

Two findings decided it:

1. **`align="start"` is what makes it work**, not `density` alone. The default
   alternates labels above and below the line, which both wraps the long labels
   at the target width ("PRD sign-/off") and makes the sequence scan badly — the
   eye has to zig-zag to read ten phases in order. `align="start"` puts every
   label on one baseline beneath its dot, and the reading order becomes plainly
   left-to-right.
2. **The failure mode is wrapping, never truncation.** Below ~1100 px the long
   labels wrap onto a second line and the row grows taller; no label is ever
   clipped or ellipsised. So the surface degrades legibly on a narrower window
   instead of hiding information, which is the property that made the fallback
   unnecessary.

**The two pre-agreed mitigations were therefore not taken.** Abbreviating the
gate labels ("CAB-1", "CAB-2", "Tech analysis") was rendered and does read fine
— but it buys nothing at the target width and costs the operator the phrase that
carries the meaning ("strategic fit", "go/no-go"). Reserve it only if the spine
is ever put in a genuinely narrow column. The vertical `v-list` fallback was
also rendered and is a perfectly usable surface, but it is not needed and it
spends vertical space the narrative feed wants.

Gate labels are distinguished by a `$shieldAlert` icon and the current phase by
a theme `dot-color`, both verified legible at `x-small`.

---

## R4. Segmented indicators: `v-progress-linear` chunks

**Decision**: use `v-progress-linear` with `chunk-count` + `variant="split"` for
both the card phase bar (`chunk-count="10"`) and the interview round indicator
(`chunk-count="<cap>"`).

**Verified available**: `node_modules/vuetify/lib/components/VProgressLinear/chunks.d.ts`
declares `ChunksProps { chunkCount, chunkWidth, chunkGap, variant: 'split' | undefined }`,
and `VProgressLinear.d.ts` exposes `chunkCount` and `variant: "split"` on the
component's props. `chunkGap` and `chunkWidth` are also available if spacing
needs tuning. No custom segmented-bar component is needed.

**Note on the degraded case** (FR-027): with no multi-round cap in force,
`chunk-count="1"` yields a single segment, which reads as a plain bar rather than
as a misleading empty progress track.

---

## R5. Recovering the interview prior art

**Decision**: restore from `3fc281c^` rather than rewrite. Confirmed present at
that commit, with the line counts the issue claims:

| Path at `3fc281c^` | Lines | Why it matters |
| --- | --- | --- |
| `frontend/src/components/QuestionnaireForm.vue` | 458 | Debounced autosave, round-advance answer reconciliation keyed on `props.round`, waiver/custom answer types, `allRequiredAnswered`, idle/dirty/saving/saved indicator — i.e. FR-022, FR-025 and FR-026 already solved once. |
| `frontend/src/lib/questionnaire.ts` | 244 | `groupByProfile` and the answer model — FR-021, FR-023. |
| `frontend/src/types/questionnaire.ts` | 86 | The answer-model types. **Not mentioned in #59** but part of the same unit; recovering the lib without it would mean re-deriving the types. |
| `frontend/src/components/RoundChips.vue` | 160 | Per-round chip grouping. **Not recovered** — see below. |
| `frontend/src/lib/debounce.ts` | 14 | Autosave timing. |
| 4 test files | 768 | `QuestionnaireForm.test.ts` (381), `questionnaire.test.ts` (237), `RoundChips.test.ts` (83), `RoundChips.interaction.test.ts` (67). |

**Rationale**: the reconciliation logic is subtle and was already tested. FR-022
and FR-025 are to be satisfied by recovering it.

**`RoundChips.vue` is deliberately *not* recovered**, despite #59 listing it.
It rendered one chip per past round for navigating between them; what FR-024
actually needs is a *cap indicator* — "round 3 of 3, last chance" — which is a chip
plus a chunked progress bar and is smaller written fresh than adapted. Its 150
lines of tests test per-round chip grouping, a behaviour this feature does not
have. Recovering it would mean carrying a component to fit a requirement it was not
built for. `RoundIndicator.vue` is new; that is intentional, not an oversight.

**Important caveat**: `QuestionnaireForm.vue` at 458 lines is within the 500-line
module cap but leaves almost no headroom, and it was written against the
pre-Phase-10 data shapes. Recovery means **port, then split** — extract the
question field (with its two escape hatches) and the round indicator into their
own components, and re-point the answer model at the current
`WorkCardGate` / `BoardInterventionRequest` shapes. A verbatim restore would
both break against the current API and land a file one edit away from violating
the cap.

---

## R6. What removing the graph actually costs

**Decision**: nothing operator-visible. Confirmed by reading it.

`lib/boardGraph.ts` (92 lines) derives node depth **purely from `dependency`
edges** (`computeDepths`, a cycle-safe longest-path), then grids nodes at fixed
spacing. `WorkflowGraph.vue` (124 lines) is a read-only navigation enhancement —
props `{ cards, relationships }`, emits `select`, calls `fitView` on mount. With
real boards being chains, the output is a horizontal line of cards.

The phase spine (R3) states the same ordering with labels and gate markers, using
a component already in the bundle. So `@vue-flow/core ^1.44.0` is a dependency
whose entire contribution is a straight line — exactly what Principle IV exists
to catch.

**Sequencing constraint**: the graph is the only structural view that exists
today. Removal is last (FR-033, User Story 5 at P5), after the board and the
spine are both in place.

---

## R7. Data available — and the five gaps a first draft missed

> **Corrected 2026-09-28.** This section originally concluded "no backend change".
> A consistency audit then found four facts the surfaces must show that **no
> response exposes**, plus one that is exposed but filtered out by default. The
> original conclusion was wrong; it is corrected below rather than quietly edited,
> because "the backend is complete" was load-bearing for the whole plan.

**Decision**: four additive read-only fields, and one frontend fix. See
`contracts/board-api-additions.md`.

Most of what the three surfaces need does already ship (landed in `31cbe6a`):

| Need | Source | Status |
| --- | --- | --- |
| Phase + stage per request | `backend/app/services/board/phases.py`; `phase`/`stage` on both `BoardSnapshot` and `BoardWorkflowSummary` (`frontend/src/types/workflows.ts:154-155,167-168`) | Present, **fetched today and rendered nowhere** — free data |
| Narrative feed events | `GET /api/board/workflows/{id}/events` (`backend/app/routers/board.py:300`), `BoardEventOut` | Present, TS type `BoardEvent` exists (`types/workflows.ts:95-101`) but **nothing imports it** |
| Artifact content | `GET /api/board/artifacts/{id}/content` (`board.py:124`) | Present and already consumed by `WorkCardDetail.vue:22` |
| Gate detail + free-text answers | `WorkCardGate { requested_decision, decision }`; `BoardInterventionRequest.answer` (`types/workflows.ts:106-109,179`) | Present, partly exercised by `WorkCardDetail.vue:76-93` |

### The five gaps

| # | Gap | Evidence | Resolution |
| --- | --- | --- | --- |
| 1 | **No decomposition parent link.** Children are re-ingested as their own workflows; the parent link is persisted in `ChildTaskLinkRow.parent_workflow_id` and exposed by no schema or router. | `backend/app/services/board/decomposition.py:134-160`; `grep parent_workflow_id` over `schemas.py` and `routers/` → nothing | FR-040 |
| 2 | **No human title.** `task_label` is `workflow.task_ref`; `Workflow.title` is on neither DTO. | `backend/app/routers/board_views.py:117,137`; `backend/app/schemas.py:184-208` | FR-041 |
| 3 | **No round or cap.** 028 touched services/config/tests only. | `grep round backend/app/schemas.py` → 0 hits; `refinement_rounds.py:4-10`; `config.py:340` | FR-042 |
| 4 | **No cap-exhausted marker.** | nothing on `WorkflowSummaryOut` marks it | FR-043 |
| 5 | **Terminal workflows filtered out by default**, for both the listing and its SSE stream; `useBoard.refresh()` passes no flag. | `backend/app/routers/board.py:228-237,242,256`; `frontend/src/composables/useBoard.ts:32-42` | FR-044 — **frontend-only**, pass `include_completed=true` |

Gap 1 is the important one: it *is* problem 1 of the spec ("decomposition children
become sibling top-level workflows"), so leaving it would have shipped a board that
still failed the epic's headline complaint. Gaps 1–4 are additive fields; gap 5 is a
missing query parameter on an existing call.

**Two further findings from the same audit**, neither needing a backend change:

- **The per-workflow SSE stream carries snapshots, not events.**
  `GET /workflows/{id}/board/events` streams the whole `BoardSnapshotOut`
  (`backend/app/routers/board.py:337-371`); `GET /workflows/{id}/events` (`:300`)
  is a plain REST list. So "live feed" means *re-fetch the event list on each
  snapshot tick*. There is no event stream to subscribe to, and any design that
  assumes one is wrong.
- **Interview questions are not an API resource.** They live as text inside the
  interview/refinement card's artifact
  (`backend/app/services/board/refinement.py:38-88`), reachable only via
  `GET /api/board/artifacts/{id}/content`. The interview surface must fetch and
  parse them (FR-045), and submit through the existing `resolve_gate` intervention's
  free-text `answer` field (FR-046).

### The thing that stays unavailable by design: recorded event attribution

`BoardEventOut.specialist`
is *derived at read time* from the card's eligible role, and is `null` for
workflow-level events and operator-resolved gates
(`backend/app/schemas.py:239-244`). No actor is recorded against an event. This
is why FR-013 exists, and the feed must not dress a derivation up as a recorded
fact. A neutral attribution for `null` — not a guessed specialist, not a blank.

**Also inherited**: every intervention echoes `expected_revision` from the
snapshot for optimistic concurrency, and a stale one returns 409
(`composables/useBoard.ts:112-131`). The action banner and the interview submit
must both surface that 409 as a human "this moved on" message, not a generic
failure — the "stale decision" edge case.

---

## R8. Where the custom-CSS line falls

**Decision**: three named gaps, and no more. FR-036 permits bespoke styling only
for a gap named and justified here.

| Gap | Why Vuetify does not cover it |
| --- | --- |
| Stage-column horizontal scroll and flex sizing | Six columns on one row that stay readable as one column fills. `v-row`/`v-col` gives a 12-unit grid, not a scrolling track with min-width columns. |
| Sticky column headers | A column header that stays put while its list scrolls. `position: sticky` on the header inside a scroll container; no Vuetify prop expresses it. |
| Independent per-pane scroll regions | The cockpit's feed and artifact rail must scroll independently of the page, each bounded. Vuetify offers no bounded-scroll-region component; `WorkBoard.vue:69-72` already carries a comment explaining why plain flexbox was chosen over `v-navigation-drawer` inside `v-main`, and the same reasoning applies. |

Anything beyond these three is a signal to reach for a Vuetify component instead.
Colour is **never** a named gap — Principle V is absolute, and every colour in
the mockups re-derives to `warning` / `success` / `error` / `primary` / `info` on
the theme.

---

## R9. Quality-harness constraints that shape the design

Not a decision so much as a set of facts that make the component split
non-optional:

- **500-line module cap, 60-line JS function cap, cognitive complexity 15.** A
  single `RequestCockpit.vue` holding spine + feed + rail + banner would breach
  the module cap; #58 warns about exactly this. The plan therefore splits every
  surface into small components from the start. New files get **no** grandfather
  exemption.
- **`knip` treats `files`/`dependencies`/`unlisted` as errors.** A new component
  that is not yet imported by anything fails the build. Consequence for task
  ordering: a component and its first consumer must land in the same task, and
  restoring `lib/questionnaire.ts` before anything imports it would break the
  gate.
- **`depcruise` forbids import cycles.** Views import components; components must
  not import views. Shared pure logic goes to `lib/`, shared state to
  `composables/`.
- **The ESLint grandfather list still names files deleted in `3fc281c`**
  (`frontend/eslint.config.js:62-92`, in a 93-line file — `WorkflowPanel.vue`,
  `useWorkflows.ts`, `lib/eventView.ts`, `lib/questionnaire.ts`,
  `QuestionnaireForm.test.ts`). Two of those names are about to exist again (R5),
  so a stale entry would silently re-exempt a *new* file. That file is CI-guarded
  by `guard-quality-config` and per `AGENTS.md` must not be edited without the
  developer's sign-off. **Out of scope here; flagged on #60 and in the plan's open
  items.**
- **The prior art is over the limits, and the exemptions say which ones.** This is
  the part that is easy to miss: `eslint.config.js:82` exempts
  `src/lib/questionnaire.ts` from **`complexity`** — so the 244-line module being
  restored exceeds cyclomatic 10 — and `:87` exempts
  `tests/components/QuestionnaireForm.test.ts` from `max-lines-per-function`, which
  is the file the interview-draft tests are seeded from. Renaming (R10) removes the
  *exemption* but not the *violation*. Recovery therefore means **port, then
  split**, for the lib and the test file as well as for the component — not just a
  rename.
- **No test coverage exists for view switching today** — `App.vue` has no
  component test. The router is new behaviour and ships with tests (Principle
  III).

---

## R10. Name the restored interview modules `interview*`, not `questionnaire*`

**Decision**: the recovered logic lands as `frontend/src/lib/interview.ts`,
`frontend/src/types/interview.ts` and `frontend/src/components/interview/*` — not
under the old `questionnaire` names.

**Rationale**: this is the mitigation for the trap in R9. The ESLint grandfather
list still names `lib/questionnaire.ts` (`complexity: 'off'`,
`frontend/eslint.config.js:82`) and `QuestionnaireForm.test.ts`
(`max-lines-per-function: 'off'`, `:87`). Restoring the prior art under its
original filenames would make **new** files silently inherit those exemptions —
precisely what `AGENTS.md` forbids ("new files get no exemptions").
The only ways out are to edit the CI-guarded config (needs the developer's
sign-off and a `[quality-override]` commit line) or to not collide with the stale
names. The second costs nothing and needs no permission.

It is also the better name on its merits: the epic, the backend and this spec all
say *interview* (`STRATEGIC_INTERVIEW`, "interview workspace", "interview
rounds"); `questionnaire` was the older vocabulary. Renaming on recovery aligns
the code with the domain language.

**Consequence**: the stale grandfather entries stay stale — they now exempt
nothing at all, which is strictly better than exempting something new. Cleaning
them up remains #60's business and still needs the developer's sign-off.

**This is only half the job.** Renaming removes the exemption; it does not remove
the violation the exemption was covering (R9). The restored lib exceeds cyclomatic
10 and the restored test exceeds the function-length limit, so both must be **split
on recovery**. A rename alone would simply trade a silent exemption for a failing
gate.

# Implementation Plan: Workflow visualisation rework

**Branch**: `work` | **Date**: 2026-09-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/029-workflow-visualisation/spec.md`

## Summary

Replace the board UI with three purpose-built surfaces — a **stage board** home
(six derived stage columns, exactly one card per ingested request), a **request
cockpit** (ten-phase spine + persona-attributed narrative feed + artifact rail +
a single action banner), and a separate input-shaped **interview workspace** —
then retire the Vue Flow graph and its dependency.

**Technical approach**: mostly frontend. The heavy prerequisites already ship
(commit `31cbe6a`): the phase/stage projection, the per-request events endpoint,
the artifact content endpoint, and gate detail with free-text answers. `phase`,
`stage` and `BoardEvent` are already fetched or declared and rendered nowhere — so
much of the rework is *displaying data the app already has*.

**But not all of it.** A consistency audit on 2026-09-28 found four facts these
surfaces must show that no response exposes: a request's human title, the
decomposition parent link, the interview round and cap, and cap exhaustion. The
parent link is the serious one — its absence *is* the epic's headline complaint
("decomposition children become sibling top-level workflows"), so a frontend-only
build would have shipped a board that still failed the thing it was built to fix.
The developer chose to add the four as additive read-only fields rather than weaken
the requirements (FR-040–FR-043, `contracts/board-api-additions.md`). A fifth gap —
terminal workflows filtered out by default — is fixed frontend-side by passing
`include_completed=true` (FR-044).

Three decisions shape everything else:

1. **Adopt `vue-router@^4.6.4`** (decided with the developer) so each surface has
   its own address and the interview can return to its cockpit. Net dependency
   change is zero — `@vue-flow/core` leaves in the same feature.
2. **Hash history, not HTML5 history** — because `StaticFiles(html=True)` does
   *not* fall back to `index.html` for deep paths, so path-based routes would work
   in dev and 404 in the bundled image. See research R2; this one is mine, not the
   developer's, and is the plan's most reversible-but-visible call.
3. **Four additive DTO fields, and nothing more** (decided with the developer on
   2026-09-28). Anything beyond them that looks like a missing field is a finding to
   raise, not to build.

## Technical Context

**Language/Version**: TypeScript 5.x (frontend); Python 3.12 (backend — four
additive DTO fields, their tests, and one comment fix)

**Primary Dependencies**: Vue 3.5.39, Vuetify 4.1.2, Vite 8.1.1. **Adding**
`vue-router ^4.6.4`. **Removing** `@vue-flow/core ^1.44.0`.

**Storage**: none added, and no schema change — so no Alembic migration. Interview
drafts live in a **module-level singleton composable keyed per workflow and round**,
not in component state: leaving the interview route unmounts the view, and FR-022
requires typed answers to survive exactly that. "Autosave" throughout means a
debounced in-memory draft commit, not persistence to a server or to
`localStorage`; drafts do not survive a browser restart.

**Testing**: Vitest + `@vue/test-utils`, `happy-dom`, configured inline in
`frontend/vite.config.ts:11-19`. All HTTP mocked (Principle III).

**Target Platform**: modern desktop browser, laptop viewport, loopback-bound
single-user deployment. Both run modes — bundled image and run-from-source —
must keep working.

**Project Type**: web application (FastAPI backend + Vue 3/Vuetify SPA)

**Performance Goals**: no measurable regression in board load. The board renders
tens of requests, not thousands; the feed must stay responsive with a large event
history (spec edge case).

**Constraints**: module ≤ 500 lines; JS function ≤ 60 lines; cyclomatic
complexity ≤ 10; cognitive complexity ≤ 15; nesting ≤ 4; copy-paste ≤ 3%. New
files get **no** grandfather exemption. Theme colours only (Principle V).

**Scale/Scope**: 5 named routes (3 of them the FR-028 surfaces, plus the sessions
panel and a not-found surface), ~25 new or recovered frontend modules, 4 source
modules deleted, 4 additive backend DTO fields, 1 dependency in / 1 out.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Assessment | Verdict |
| --- | --- | --- |
| **I. Contract Fidelity** | Four DTOs gain an additive read-only field each (FR-040–FR-043). Principle I is satisfied **only if** `backend/app/schemas.py` and `frontend/src/types/workflows.ts` change in the *same commit* — "changing one side without the other is prohibited" — and `specs/026-autonomous-work-board/contracts/board-api.md` is amended in that commit too. Recorded in `contracts/board-api-additions.md`. Everything else is consumed unchanged, and all new view models are frontend-only with no server counterpart (`data-model.md` §1/§3 vs §2). | **PASS with a binding condition** |
| **II. Layered, Backend-Owned Architecture** | No business logic moves to the frontend, and the four additions deliberately keep it that way: cap exhaustion (FR-043) is exposed as a *fact the backend judges* rather than something the client infers, and the parent link (FR-040) is read, never computed. Stage placement comes from the server's `stage` field, never re-derived locally; the phase projection stays display-only and never becomes a driver (FR-039, `phases.py:1-9`). Answer validation is UX-only — the backend stays the authority and its 409 on a stale `expected_revision` is surfaced, not second-guessed. No schema change, so no Alembic question. | **PASS** |
| **III. Test-First Discipline** | Every behavioural rule lands in a pure `lib/` module so it is directly unit-testable: attention precedence, phase position, persona attribution, answer-state gating. Router behaviour is new and ships with tests — note `App.vue`'s view switching is **untested today**, so this is a coverage increase. All HTTP mocked. | **PASS** |
| **IV. Deliberate Simplicity & Single-User Scope** | One dependency added, one removed — see Complexity Tracking. Deliberate refusals of generality: artifact content is a dialog rather than its own route; no state-management library; no mobile layout; no multi-user concern. | **PASS with justification** |
| **V. Kit-Aligned Consistency & Observability** | Built from Vuetify components, with exactly three named custom-CSS gaps (research R8) and no others. Theme colours only — every mockup colour re-derives to `warning`/`success`/`error`/`primary`/`info`. State stays in module-level singleton composables, not Pinia, per the resolved kit. No secrets in addresses (FR-032). | **PASS** |

**Post-Phase-1 re-check**: one material change. The audit's discovery that four
facts are unexposed turned Principle I from a clean PASS into a **PASS with a
binding condition** (both sides of the type contract in one commit) and added a
fourth Complexity Tracking row. Principle IV is unaffected in substance: the
additions are the *minimum* needed to keep requirements the developer chose not to
cut, and each was checked for a client-side workaround first — there is none for
any of the four.

The design also added one refusal (artifact-as-dialog) and one avoidance
(`interview*` naming, research R10, sidestepping a stale grandfather entry without
editing CI-guarded config). Both reduce complexity rather than adding it.

## Project Structure

### Documentation (this feature)

```text
specs/029-workflow-visualisation/
├── spec.md                      # Feature specification
├── plan.md                      # This file
├── research.md                  # Phase 0 — R1..R10
├── data-model.md                # Phase 1 — existing types vs new view models
├── quickstart.md                # Phase 1 — how to run and prove it
├── contracts/
│   └── routes.md                # Phase 1 — address + surface-composition contract
├── checklists/
│   └── requirements.md          # Spec quality checklist
└── tasks.md                     # Phase 2 (/speckit.tasks — not created here)
```

### Source Code (repository root)

```text
frontend/src/
├── router/
│   └── index.ts                     # NEW  routes, hash history, guards
├── views/                           # NEW  directory: one component per route
│   ├── StageBoardView.vue           # NEW  US1
│   ├── RequestCockpitView.vue       # NEW  US2
│   ├── InterviewView.vue            # NEW  US3
│   ├── SessionsView.vue             # NEW  wraps SessionPanel (FR-047)
│   └── NotFoundView.vue             # NEW  not-found + unknown id (FR-030)
├── components/
│   ├── board/                       # NEW
│   │   ├── StageColumn.vue
│   │   ├── RequestCard.vue
│   │   └── RequestSubItems.vue
│   ├── cockpit/                     # NEW
│   │   ├── ActionBanner.vue
│   │   ├── PhaseSpine.vue
│   │   ├── NarrativeFeed.vue
│   │   ├── FeedEntry.vue
│   │   ├── ArtifactRail.vue
│   │   └── ArtifactDialog.vue
│   ├── interview/                   # NEW  (recovered from 3fc281c^, split)
│   │   ├── PersonaQuestionGroup.vue
│   │   ├── QuestionField.vue
│   │   └── RoundIndicator.vue
│   ├── common/
│   │   └── PhaseProgress.vue        # NEW  shared chunked bar
│   ├── WorkBoard.vue                # DELETE (US5)
│   ├── WorkflowGraph.vue            # DELETE (US5)
│   └── WorkCardDetail.vue           # absorbed by banner + dialog, then removed
├── composables/
│   ├── useBoardEvents.ts            # NEW  feed fetch + live subscription
│   ├── useInterviewDraft.ts         # NEW  draft + autosave + reconciliation
│   └── useBoard.ts                  # extended, not replaced
├── lib/
│   ├── stages.ts                    # NEW  pure: stage/phase order, attention
│   ├── personas.ts                  # NEW  pure: event → attribution + tone
│   ├── interview.ts                 # RECOVERED from lib/questionnaire.ts
│   ├── debounce.ts                  # RECOVERED verbatim
│   ├── deeplink.ts                  # retained; select() now navigates
│   └── boardGraph.ts                # DELETE (US5)
├── types/
│   └── interview.ts                 # RECOVERED from types/questionnaire.ts
├── App.vue                          # shell only; view toggle → RouterView
└── main.ts                          # registers the router

frontend/tests/                       # mirrors src/ one-to-one, as today

backend/app/
├── schemas.py                        # 4 additive read-only fields (FR-040..FR-043)
├── routers/board_views.py            # populate them in the projections
├── routers/board.py                  # expose the parent link on the listing
└── main.py                           # comment-only fix at :249-251 (research R2)

backend/tests/                         # pytest for each addition
specs/026-autonomous-work-board/contracts/board-api.md   # amended (Principle I)
docs/mockups/*.png                    # now tracked (.gitignore negation in place)
```

**Structure Decision**: a `views/` directory is introduced because routes need
route components, and mixing them into the flat `components/` directory would
blur the `depcruise` rule that keeps the dependency direction one-way (views →
components → composables → lib → types). Per-surface subdirectories under
`components/` keep each surface's parts together; this matters because the
500-line cap forces roughly six components per surface, and a flat directory of
twenty siblings loses the grouping. `frontend/tests/` mirrors `src/` exactly, as
it already does.

## Phased delivery

Ordered so each phase is independently demonstrable and nothing is removed before
its replacement works.

| Phase | Delivers | Maps to |
| --- | --- | --- |
| **A0. API additions** | The four additive DTO fields, both sides of the type contract, backend tests, and the contract amendment. Nothing visual. First because B and D cannot be built without them. | FR-040..FR-043 |
| **A. Router foundation** | `vue-router`, hash history, five named routes, `?run=` compatibility, `App.vue` shell keeps existing surfaces behind routes. No visual change. | US4 (FR-028..FR-032, FR-047) |
| **B. Stage board** | `lib/stages.ts` + board components; becomes the `board` route, **retiring the nav list at that point**. | US1 (FR-001..FR-009, FR-044) |
| **C. Request cockpit** | Spine (with the R3 legibility gate), feed, rail, banner. `lib/personas.ts`, `useBoardEvents.ts`. | US2 (FR-010..FR-019) |
| **D. Interview workspace** | Recover and split the prior art; both escape hatches; round cap display; return-to-cockpit. | US3 (FR-020..FR-027) |
| **E. Retirement** | Delete graph, `boardGraph.ts`, `@vue-flow/core`, `WorkBoard.vue`, the toggle, `WorkCardDetail.vue`. Fix the `main.py` comment. | US5 (FR-033..FR-035) |

A0 first because the board (B) cannot nest decomposition children or show titles
without it, and the interview (D) cannot show a round cap. Then A, because B–D all
navigate and retrofitting routing afterwards would mean rewriting every navigation
call site twice.

## Complexity Tracking

> Constitution Principle IV requires added complexity to be justified with the
> simpler alternative and why it was rejected.

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| **New dependency: `vue-router ^4.6.4`** | Five surfaces need their own addresses (FR-028), the browser's back control must retrace the path (FR-029), the interview must return to its cockpit by name (FR-020), an unknown id must be caught and explained (FR-030), and existing `?run=` links must keep working (FR-031). Today's mechanism is a two-value `ref` plus a 26-line read-only query parser that never writes the URL and has no `popstate` listener. | **Extending `lib/deeplink.ts` with `?view=`** was considered and rejected by the developer on 2026-09-28: it means hand-writing URL writes, history entries, `popstate` handling, parameter parsing and back-button semantics — reimplementing a router, less well, and owning its edge cases in our own tests. **Keeping the plain `ref`** cannot satisfy FR-028–FR-031 at all. Mitigations that make the cost near-zero: the v4 line is chosen over v5 precisely to avoid surplus surface (v5 carries optional `pinia`/`@pinia/colada` peers this project's conventions prohibit, at double the unpacked size), and `@vue-flow/core` is removed in the same feature — so the frontend's production dependency count does **not** increase. |
| **New `views/` directory (a fourth frontend layer)** | Route components are a distinct kind from leaf components, and `depcruise` enforces a one-way dependency graph. | **Putting route components in `components/`** was rejected because it makes the views→components rule unexpressible as a path-based `depcruise` constraint, leaving the no-cycle guarantee to reviewer vigilance instead of the harness. |
| **~25 modules where 3 surfaces might suggest 3** | The 500-line module cap and 60-line function cap are hard constraints; #58 warns specifically that a single cockpit module would breach them. | **Three large components** would violate the cap, and the only ways to pass would be a suppression, a threshold edit, or a grandfather entry — all three explicitly forbidden by `AGENTS.md`. Splitting up front is cheaper than refactoring under a failing gate later. |
| **4 additive fields on existing board DTOs** (FR-040..FR-043) | Four facts the surfaces must show are exposed by no response: human title, decomposition parent link, interview round/cap, cap exhaustion. Each was checked for a client-side workaround; **none exists** — the parent relationship is absent from every response, the round is a server derivation, the cap is server config, and cap exhaustion is a pipeline judgement. Without FR-040 the board still shows decomposition children as siblings, which is the epic's headline complaint. | **Weakening the four requirements** (cut the title, nest only in-workflow cards, drop the round indicator, drop the `cap-reached` treatment) was the alternative, and was rejected by the developer on 2026-09-28 because it leaves epic #40's problem 1 unfixed and makes #59's round-cap display impossible. **Splitting them into a predecessor issue** was also rejected — it serialises the work and blocks #57/#58/#59 behind a new unplanned issue. Kept minimal: additive and read-only, no endpoint, no field changes meaning, nothing writable. |

## Open items for the developer

Neither blocks Phase A; both want a decision before the phase that hits them.

1. **Hash vs clean URLs** (research R2). I chose hash history so the bundled
   image and the dev server behave identically without a backend change, at the
   cost of `/#/requests/<id>` in the address bar. The alternative is a backend SPA
   catch-all plus its test, for cleaner URLs. If the URL aesthetics matter more
   than the frontend-only boundary, say so before Phase A lands.
2. **Stale ESLint grandfather entries** (research R9, tracked on #60).
   `frontend/eslint.config.js:60-95` still names `lib/questionnaire.ts` and
   `QuestionnaireForm.test.ts`. Research R10 sidesteps the trap by naming the
   recovered modules `interview*`, so **no new file inherits a stale exemption**
   and no CI-guarded file needs editing. Cleaning the dead entries still needs
   your sign-off and a `[quality-override]` commit line; it stays out of scope
   here.

## Deliberately out of scope

Workflow behaviour of any kind; the phase projection becoming a driver (FR-039);
the agent-session debug panel's *contents* (its reachability is in scope, FR-047);
notification *generation* (following an existing notification is in scope);
**any API change beyond the four additive fields** — a further gap found during
implementation is a finding to raise, not to fill opportunistically (research R7,
which was wrong once already and is now explicit); new endpoints; mobile layout;
`RoundChips.vue` recovery (research R5 explains why the round indicator is new);
and the grandfather-list cleanup above.

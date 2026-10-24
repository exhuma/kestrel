# Contract: Navigation & surface composition

**Feature**: `specs/029-workflow-visualisation` | **Date**: 2026-09-28

This file is the **UI contract**: the addresses the application answers to, and
the component boundaries each surface is assembled from.

The feature adds **no endpoint**, but it does add four additive read-only fields
to existing board responses — see
[`board-api-additions.md`](./board-api-additions.md). The API contract of record
remains `specs/026-autonomous-work-board/contracts/board-api.md`, which those
additions amend rather than replace.

---

## 1. Address contract

History mode is **hash-based** (research R2), so every path below is reached as
`/#<path>`. Written as paths here because that is how they appear in the router.

| Name | Path | Renders | Guard / failure behaviour |
| --- | --- | --- | --- |
| `board` | `/` | Stage board | — |
| `cockpit` | `/requests/:id` | Request cockpit | Unknown `id` → explanatory message + route back to `board` (FR-030). Never a blank page or a raw error. |
| `interview` | `/requests/:id/interview` | Interview workspace | Unknown `id` → as above. A request with no open interview → redirect to its `cockpit`, which states what it *is* waiting on. |
| `sessions` | `/sessions` | Existing agent-session debug panel | Unchanged surface, now addressable instead of toggle-only. |
| `not-found` | `/:pathMatch(.*)*` | Not-found notice | Offers a route to `board`. |

### Guarantees

1. **Direct resolution** — each address renders its surface in a fresh session
   without first rendering the board (FR-028).
2. **History fidelity** — `board → cockpit → interview` is retraced in reverse by
   the browser's back control (FR-029). Navigations are history *pushes*;
   the legacy redirect in §2 is a *replace*, so back never lands on it.
3. **Legacy compatibility** — `/?run=<id>` (no hash route present) resolves to
   `cockpit` for that `id` (FR-031), via a history-replacing redirect.
4. **No secrets in addresses** — the only parameter is an opaque workflow id,
   which is already what today's `?run=` carries (FR-032, and the constitution's
   existing constraint on notification deep-links).
5. **Lazy surfaces** — `sessions` stays lazily loaded, as it is today; `cockpit`
   and `interview` are lazily loaded too, so the board (the common entry point)
   does not pay for them.

### Return-path contract

The interview's submit returns to the cockpit **by named route** (`cockpit`, with
the same `id`), not by a history `back()`. `back()` would be wrong whenever the
operator arrived by a bookmark or a notification link — there would be nothing
behind it (FR-020, User Story 3 scenario 8).

---

## 2. Bootstrap sequence

Replaces the current one-shot `applyDeepLink` call at `frontend/src/main.ts:51`.

```
1. create the Vuetify plugin            (unchanged)
2. create the router                    (new; hash history)
3. resolve the legacy ?run= parameter:
     runIdFromSearch(window.location.search)
       → if present AND no hash route is given
       → router.replace({ name: 'cockpit', params: { id } })
4. mount the app
```

`lib/deeplink.ts` keeps its present signature — `runIdFromSearch(search)` and
`applyDeepLink(search, select)` — so `frontend/tests/lib/deeplink.test.ts` stays
valid. Only the injected `select` callback changes: it performs a route
navigation instead of a board selection. The module stays free of `window` and
router coupling, which is why it was written with an injected callback in the
first place.

---

## 3. Surface composition contract

Component boundaries are part of the contract because the 500-line module cap and
the 60-line function cap make them load-bearing, not stylistic (research R9). New
files get **no** grandfather exemption.

### Stage board — `views/StageBoardView.vue`

| Component | Responsibility |
| --- | --- |
| `views/StageBoardView.vue` | Route component: owns the column track, the empty state, the error alert, and the list subscription lifecycle. |
| `components/board/StageColumn.vue` | One stage column: sticky header, count, scrolling body. |
| `components/board/RequestCard.vue` | One request: identity, phase line, attention treatment, actions. |
| `components/board/RequestSubItems.vue` | The request's own cards, nested inside it (FR-002). |
| `components/common/PhaseProgress.vue` | `v-progress-linear chunk-count="10" variant="split"`. Shared with the cockpit. |
| `lib/stages.ts` | **Pure**: stage order, phase order, `phasePosition()`, `attentionOf()` with its precedence rule, `groupByStage()`. |

`lib/stages.ts` is where the board's logic is *tested* — the components render it.
That is what keeps the components under the function-length cap and the rules
directly unit-testable.

### Request cockpit — `views/RequestCockpitView.vue`

| Component | Responsibility |
| --- | --- |
| `views/RequestCockpitView.vue` | Route component: loads the snapshot, lays out the four regions, owns the not-found path. |
| `components/cockpit/ActionBanner.vue` | The single ask (FR-016). Renders nothing when nothing is pending. |
| `components/cockpit/PhaseSpine.vue` | Ten labelled phases, gates marked distinctly (FR-011). Subject to the R3 legibility gate. |
| `components/cockpit/NarrativeFeed.vue` | Chronological feed; owns auto-scroll and its suppression (FR-018). |
| `components/cockpit/FeedEntry.vue` | One row: persona avatar, attribution, tone, summary. |
| `components/cockpit/ArtifactRail.vue` | The durable artifact set with states (FR-014). |
| `components/cockpit/ArtifactDialog.vue` | Artifact content as text, with provenance (FR-015). |
| `composables/useBoardEvents.ts` | Singleton-per-workflow fetch + live subscription for `BoardEvent`. |
| `lib/personas.ts` | **Pure**: `BoardEvent` → `PersonaLabel` + tone + summary, with the neutral case explicit (FR-013). |

The feed's idiom is **reused, not reinvented**: `SessionPanel.vue:325-368` already
establishes auto-scroll-on-new-event, a tone map and a compact timeline. Diverging
from it would leave the app with two feed idioms.

### Interview workspace — `views/InterviewView.vue`

| Component | Responsibility |
| --- | --- |
| `views/InterviewView.vue` | Route component: form shell, submit, return-to-cockpit navigation. |
| `components/interview/PersonaQuestionGroup.vue` | One persona's questions (FR-021). |
| `components/interview/QuestionField.vue` | One question with both escape hatches (FR-023). |
| `components/interview/RoundIndicator.vue` | Current round, cap, and the final-round warning (FR-024, FR-027). |
| `composables/useInterviewDraft.ts` | Draft state, debounced autosave, round-advance reconciliation (FR-022, FR-025). |
| `lib/interview.ts` | **Pure**: grouping, answer model, `allRequiredAnswered` (FR-026). |
| `types/interview.ts` | Answer-model types. |
| `lib/debounce.ts` | Recovered verbatim; 14 lines, no adaptation needed. |

Named `interview*` rather than `questionnaire*` deliberately — research R10.

### Shell surfaces

| Component | Responsibility |
| --- | --- |
| `views/SessionsView.vue` | Thin route wrapper around the existing `SessionPanel.vue`, keeping it lazily loaded with `PanelLoading` / `PanelError`. Exists because removing the view toggle would otherwise orphan the debug panel (FR-047). |
| `views/NotFoundView.vue` | The `not-found` route's surface, and the target for an unknown request id: an explanatory message and a route back to the board (FR-030). |

### Dependency direction (enforced by `depcruise`)

```
views/  →  components/  →  composables/  →  lib/  →  types/
             ↘ common/                        ↗
```

Downward only. No component imports a view; no `lib/` module imports a component.
Shared pure logic lives in `lib/`, shared state in `composables/`.

---

## 4. Removal contract

| Removed | Replaced by |
| --- | --- |
| `components/WorkflowGraph.vue` | `components/cockpit/PhaseSpine.vue` |
| `lib/boardGraph.ts` | — (its only consumer was the graph) |
| `tests/components/WorkflowGraph.test.ts`, `tests/lib/boardGraph.test.ts` | Spine + board tests |
| `@vue-flow/core` dependency | — |
| `components/WorkBoard.vue` and its list/graph toggle | `views/StageBoardView.vue` |

`WorkCardDetail.vue` is removed **last, and only by absorption**: its
gate-decision logic (`WorkCardDetail.vue:76-93`) and artifact fetch (`:22`) are the
working basis for the action banner and the artifact dialog. It may not be deleted
until both have demonstrably taken over that behaviour — it is superseded, not
simply dropped.

**Ordering constraint**: nothing in this table may be removed before its
replacement is in place and passing tests (FR-033, User Story 5 at P5).

---

## 5. Verification

| Guarantee | How it is verified |
| --- | --- |
| Every route resolves directly | Router unit test per route name, mounted from a cold router |
| Back retraces the path | Router history test walking board → cockpit → interview |
| `?run=` still resolves | Existing `deeplink.test.ts` plus a bootstrap redirect test |
| Unknown id is explained | Route guard test asserting the message and the route back |
| Attention precedence | `lib/stages.ts` unit test over cards qualifying for several states |
| Neutral attribution | `lib/personas.ts` unit test with `specialist: null` |
| Required-answer gating | `lib/interview.ts` unit test over each answer state |
| Round reconciliation | `useInterviewDraft.ts` test advancing the round with answers present |
| No new dead code / cycles | `npm run knip`, `npm run depcruise` |
| Whole gate | `task quality` |

All HTTP is mocked (Principle III). No test touches a real backend.

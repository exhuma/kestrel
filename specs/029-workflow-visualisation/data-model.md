# Phase 1 Data Model: Workflow visualisation rework

**Feature**: `specs/029-workflow-visualisation` | **Date**: 2026-09-28

This feature **persists nothing**. It adds four additive read-only fields to
existing responses (§3) and otherwise consumes types unchanged. Every type below
is one of three kinds:

1. **Existing, consumed unchanged** (§1) — must not drift from the backend.
2. **Existing, extended additively** (§3) — both sides change in the same commit,
   per constitution Principle I.
3. **New frontend view models** (§2) — ours alone, no server counterpart, covered
   by unit tests rather than by a contract.

---

## 1. Existing types consumed (no change permitted)

| Type | Fields this feature reads | Used by |
| --- | --- | --- |
| `BoardWorkflowSummary` | `id`, `task_label`, `status`, `phase`, `stage`, `state_counts`, `action_required_count` | Stage board |
| `BoardSnapshot` | `workflow`, `cards`, `relationships`, `phase`, `stage`, `state_counts`, `revision` | Cockpit |
| `WorkCardSummary` | `id`, `card_type`, `state`, `gate`, `latest_artifact` | Board sub-items, cockpit rail |
| `WorkCardGate` | `requested_decision`, `decision` | Action banner, interview |
| `BoardEvent` | `event_type`, `card_id`, `payload`, `created_at`, `specialist` | Narrative feed |
| `BoardArtifactContent` | `content`, `trust` | Artifact dialog, interview question set |
| `BoardInterventionRequest` | `action`, `decision`, `answer`, `expected_revision` | Action banner, interview submit |

Notes that cost time if missed:

- The card's kind field is **`card_type`**, not `kind`
  (`frontend/src/types/workflows.ts:115`).
- `state_counts` is needed for the `quarantined` attention treatment; it is on
  both the summary and the snapshot.
- `BoardEvent` is declared but imported by nothing — this feature is its first
  consumer. `phase` and `stage` are likewise fetched today and rendered nowhere.
- **The per-workflow SSE stream carries the whole snapshot, not events**
  (`backend/app/routers/board.py:337-371`). `GET /workflows/{id}/events` is a
  plain REST list. "Live feed" therefore means *re-fetch the event list on each
  snapshot tick*, not subscribe to an event stream. There is no event SSE to
  subscribe to.
- The listing **omits terminal workflows unless `include_completed=true`**
  (`backend/app/routers/board.py:228-237`, and the same for the SSE stream).
  `useBoard.refresh()` passes neither today. The Done column depends on this
  (FR-044).

**Invariant**: beyond the four additions in §3, if a requirement appears to need
another new field, that is a finding to raise with the developer — not a licence
to keep extending the API.

---

## 2. New view models (frontend-only, pure, derived)

### `Stage` — the board's column axis

Six ordered columns, mirroring `_STAGE_BY_PHASE` in
`backend/app/services/board/phases.py`:

```
1. Intake & alignment    (phases: Intake, Understanding)
2. Discovery             (phases: CAB-1 - strategic fit, Pre-assessment)
3. Definition            (phases: PRD, PRD sign-off)
4. Planning              (phases: Technical analysis, CAB-2 - go/no-go)
5. Build & deliver       (phases: Build, Delivery)
6. Done                  (synthetic; the "done" phase)
```

**Duplication risk, and how it is handled.** This ordering exists in the backend
already. The frontend needs it to lay out columns, and the server does not send
it. Rather than hard-code a second copy of the *phase→stage* mapping (which would
drift), the frontend hard-codes only:

- the **six stage names in order** (needed for column layout), and
- the **ten phase names in order** (needed for the spine and for the position
  indicator).

It derives a request's column from the `stage` field the server already sends —
never by re-deriving stage from phase locally. So the frontend owns presentation
order only; the mapping stays single-sourced in the backend.

**Validation rule**: a `stage` value the frontend does not recognise must be
surfaced, not dropped. It renders in a trailing "Unknown stage" column rather
than making a request vanish from the board — the FR-002 guarantee is that every
request appears exactly once, and a strict filter would violate it on any future
backend addition.

### `PhasePosition` — position within the ten-phase sequence

```
{ ordinal: number | null, total: 10, isTerminal: boolean, label: string }
```

Derived from the `phase` string. `ordinal` is `null` for an unrecognised phase —
which renders the label verbatim with no position bar, per the spec's edge case,
rather than defaulting to 0 (reads as "not started") or crashing.

`isTerminal` is true for the synthetic `done` phase, which drives the Done column
and a full progress bar.

### `BoardRequest` — one board card

The unit of FR-002: exactly one per ingested request.

```
{
  summary:   BoardWorkflowSummary,
  position:  PhasePosition,
  attention: AttentionState,
  subItems:  SubItem[],
}
```

`subItems` covers **two different things**, which is easy to get wrong:

1. The request's **own cards** (interview personas, implementation items),
   flattened to a label + state — available on the snapshot today.
2. Its **decomposition children**, which are *separate workflows* with their own
   source refs, matched via the FR-040 parent link.

Both render **inside** the parent's card. Deliberately not a recursive tree: the
board shows one level of nesting, and the cockpit is where full detail lives.

**A child whose parent is not in the listing falls back to top-level.** FR-002
guarantees each request appears exactly *once*, not *at most* once — nesting a
child under an absent parent would make it vanish.

### `AttentionState` — the card's visual treatment

A **closed set**, because FR-005 requires three treatments that are not
interchangeable and a union type is what stops them blurring:

| Value | Meaning | Theme colour |
| --- | --- | --- |
| `none` | Progressing; nothing wanted | default |
| `your-move` | A gate awaits the operator | `warning` |
| `cap-reached` | Round cap hit without a usable answer | `error` |
| `quarantined` | Held at intake by security review | `error`, distinct iconography |
| `done` | Terminal | `success` |

**Precedence rule** (a card can qualify for more than one): `quarantined` >
`cap-reached` > `your-move` > `done` > `none`. Quarantine outranks everything
because it is the one state where the request is not what it appears to be.
This precedence is a pure function and is unit-tested directly.

**Inputs each treatment is derived from** — spelled out because two of them are
not obvious, and one did not exist before §3:

| Treatment | Derived from |
| --- | --- |
| `quarantined` | `state_counts` (a security-review card in a holding state) |
| `cap-reached` | the cap-exhausted marker of **FR-043** — not inferable client-side |
| `your-move` | `action_required_count > 0` |
| `done` | `phase === 'done'` |

### `FeedEntry` — one narrative feed row

```
{
  event:     BoardEvent,
  persona:   PersonaLabel,
  tone:      'info' | 'success' | 'warning' | 'error',
  summary:   string,
  timestamp: string,
}
```

### `PersonaLabel` — attribution, honestly

```
{ kind: 'specialist', name: string } | { kind: 'system' } | { kind: 'operator' }
```

The three-way split is FR-013 made structural. `BoardEvent.specialist` is `null`
for workflow-level events and for gates the operator resolved, and it is a
**read-time derivation from the card's eligible role, not a recorded actor**
(`backend/app/schemas.py:239-244`). A plain `string | null` would invite rendering
`null` as an empty name or picking an arbitrary one; the tagged union forces the
neutral case to be handled. `operator` is inferred from event type, never from the
`specialist` field.

### `ArtifactRailItem` — one durable artifact

```
{ id, kind, label, state, icon, available: boolean }
```

The rail lists the **expected** artifact set from FR-014 (original request,
understanding check, CAB-1 decision, interview rounds, PRD, technical analysis,
executive summary, pull request) in pipeline order, with `available: false` for
those a request has not produced yet. A rail that only listed what exists would
hide what is still to come — the rail's job is to show the durable shape of the
work, not just its current contents.

### `InterviewDraft` / `QuestionAnswer` — recovered, then adapted

Recovered from `3fc281c^` per research R5, renamed per R10. The answer model must
carry three distinguishable states so FR-023 cannot collapse into "empty":

| State | Meaning |
| --- | --- |
| `answered` | Substantive text |
| `unknown` | "I don't know — let the PRD state an assumption" |
| `not-relevant` | Does not apply; does not block submission |
| `unanswered` | Nothing recorded yet; blocks submission if required |

**Validation rules**:

- `answered` requires non-empty trimmed text. Whitespace is `unanswered`.
- `unknown` and `not-relevant` carry no text and MUST NOT be serialised as an
  empty answer — they are distinct intents the PRD step reads differently.
- Submission is refused while any required question is `unanswered` (FR-026).
- On round advance, answers are reconciled against the new round's questions by
  question identity, keyed on round — the logic recovered from
  `QuestionnaireForm.vue`, not rewritten (FR-025).

### `RoundState` — the cap indicator

```
{ current: number, cap: number }
```

`cap` of 1 is the valid degraded case (FR-027). `current === cap` is what drives
the "final round before assumptions are recorded" wording (FR-024) — the wording
is a function of the state, not a separate flag, so the two cannot disagree.

**Source**: the gate's `{ round, cap }` from **FR-042**. Neither value is
available from any response today, and neither is derivable client-side: the round
is computed server-side and the cap is server configuration. A `null` means the
gate is not round-capped, which renders as a single round rather than as a
zero-of-zero.

### `InterviewQuestionSet` — what is being answered

The questions are **not** a first-class API resource. They live as text inside the
interview/refinement card's artifact, reachable only through
`GET /api/board/artifacts/{id}/content` (`backend/app/services/board/refinement.py:38-88`).

So the interview surface must fetch the artifact content and parse the question
set out of it, and FR-045 requires that a content it cannot read is **stated**,
not rendered as an empty interview. Parsing text into a question list is a pure
function and belongs in `lib/interview.ts` where it can be tested against real
artifact samples.

**Submit direction** (FR-046): answers go back through the existing
`resolve_gate` intervention as the free-text `answer` field, carrying
`expected_revision`. Because that is a *single* text field, the four answer states
must be serialised into it in a form the PRD step can tell apart — an "I don't
know" and a "not relevant" must not both arrive as empty text. The serialisation
format is a decision the implementing task must record, not improvise.

**Recorded format** (T070, `lib/interviewAnswers.ts::serializeAnswers`): one
`Q:`/`A:` block per question, blocks separated by a blank line —

```
Q: <question prompt>
A: <trimmed answer text>

Q: <question prompt>
A: (I don't know — let the PRD state an assumption.)
```

`unknown` and `not-relevant` each get their own fixed, human-readable `A:`
line (never blank), so the three non-empty outcomes stay distinguishable to
both a human reading the artifact later and the `pm` agent drafting the next
round or the PRD — plain text, not JSON, since the consumer on the other end
is always an LLM prompt (`refinement_rounds.py::_prior_round_answers`
threads the previous response artifact's content in verbatim), never a
machine parser.

**Persona derivation gap, found while implementing** (parallel to FR-039):
`WorkCardSummaryOut` carries no persona for a `refinement_gate` card — the
card itself has no `eligible_roles` (see `refinement_rounds.py`'s module
docstring). The only signal available client-side is the card's `title`,
which `refinement.py::route_refinement_result` constructs as
`f"{persona} interview (...)"`. `lib/interview.ts::personaOf` parses that
prefix (falling back to `'requester'` for the un-prefixed CAB-1
strategic-fit title and for anything else unrecognised), which is
sufficient for FR-021 today but couples the frontend to a string built for
display, not parsing. A dedicated `persona` field on `WorkCardGateOut`
would be the clean fix; raised here rather than decided unilaterally, same
as FR-039.

---

## 3. Existing types extended (additive, read-only)

Four fields, each closing a gap that would otherwise force a requirement to be
weakened. All are **additive**: nothing is renamed, no existing field changes
meaning, no endpoint is added, nothing becomes writable. Per Principle I the
backend schema and `frontend/src/types/workflows.ts` change in the **same**
commit, with a contract note in
`specs/026-autonomous-work-board/contracts/board-api.md`.

| # | Field | On | Source already in the backend | Unblocks |
| --- | --- | --- | --- | --- |
| FR-040 | parent request identity, nullable | `WorkflowSummaryOut` | `ChildTaskStore.parent_workflow_id(task_ref)` — a lookup that already exists, exposed by no response | FR-002 nesting of decomposition children |
| FR-041 | human title | `WorkflowSummaryOut`, `BoardSnapshotOut` | `Workflow.title` (`backend/app/models_board.py:147`, "safe display title after input acceptance", already used at `delivery.py:43`) — on neither DTO | FR-003 |
| FR-042 | `{ round, cap }`, nullable | the gate detail on `WorkCardSummaryOut` | round derived in `refinement_rounds.py`; cap is `board_refinement_round_cap` config | FR-024, FR-027 |
| FR-043 | cap-exhausted marker | `WorkflowSummaryOut` | derivable server-side from round state | FR-005 `cap-reached` |

**Why these four and not a general-purpose expansion.** Each is the *minimum* fact
needed to satisfy a requirement the developer chose to keep. FR-040 is the one
that matters most: the parent link is why decomposition children still read as
siblings, which is problem 1 of this spec. Exposing a nullable parent id is a
smaller change than any client-side workaround, and a client-side workaround is
impossible anyway — the relationship is simply absent from every response.

**Nullability is meaningful, not incidental**: a `null` parent means "not
decomposed from anything", `null` round/cap means "not a round-capped gate"
(FR-027's degraded case), and the frontend must handle each rather than treat
absence as zero.

---

## 4. Route model

The addressability contract. See `contracts/routes.md` for the full table.

| Route name | Path | Params |
| --- | --- | --- |
| `board` | `/` | — |
| `cockpit` | `/requests/:id` | `id` = workflow id |
| `interview` | `/requests/:id/interview` | `id` |
| `sessions` | `/sessions` | — |
| `not-found` | `/:pathMatch(.*)*` | — |

Addresses are hash-based (research R2), so these render as `/#/requests/<id>`.

**Legacy compatibility (FR-031)**: `?run=<id>` in the query string with no hash
route resolves to `cockpit` with that `id`. `lib/deeplink.ts` is retained for
this and keeps its current signature — its existing test stays valid — with the
`select` callback now performing a route navigation instead of a board selection.

**Not addressable, deliberately**: artifact content opens as a dialog within the
cockpit rather than at its own address. FR-028 requires addresses for the board,
cockpit and interview only; giving a modal its own route is speculative
generality (Principle IV) and costs a route-guard for a transient surface.

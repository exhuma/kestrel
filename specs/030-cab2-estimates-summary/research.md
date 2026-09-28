# Research: CAB-2 estimates, coding/manual split, and executive summary

All product-level questions were settled with the developer before the spec
(see spec.md, "Decisions settled"). This file records the implementation
decisions the plan rests on. Each entry gives the decision, why, and what was
rejected.

## R1. How estimates are stored (FR-016)

**Decision**: When the estimation result is valid, the pm's candidate and the
developer's estimates are merged into one JSON document, the **CAB-2
proposal**. It is stored as a reference artifact (`logical_name =
"cab2_proposal"`, `trust = "agent_output"`) produced by the estimation card.
The CAB-2 gate's `target_artifact_id` points at it. Publishing already reads
the gate's target, so it gets tasks and estimates from one place.

**Why**: estimates stay machine-readable and are keyed by workflow (through
the producer card) and by `task_node_id`. Published children already record
their `task_node_id` in `child_task_link`, so a later estimate-vs-actual
feature can join children to their estimates without parsing prose. No schema
change is needed.

**Rejected**:
- A dedicated `task_estimate` table. It would be more queryable but needs an
  Alembic migration, a store and a port, for data that has no reader until the
  actual-usage follow-up exists (Principle IV). That follow-up can promote the
  JSON to a table once it has a real query to serve.
- Two artifacts (candidate plus a separate estimates document). The gate has
  one target, and publishing would need to find the second artifact by
  convention.

## R2. How the estimation card finds its candidate

**Decision**: When decomposition is routed, the estimation card is created
with a `dependency` relation on the decomposition card that produced the
candidate. Both the estimation envelope and estimation routing follow that
edge and read `decomposition_candidate` from the dependency's card.

**Why**: the link is explicit and survives retries. It also shows up in the
board's relationships the same way every other dependency does. The
decomposition card is already done, so the edge never blocks readiness.

**Rejected**: "the latest decomposition card in the workflow" is implicit and
wrong if decomposition were ever re-run.

## R3. Where the executive summary lives and how the gate shows it

**Decision**: The summary is rendered as Markdown and stored as a reference
artifact (`logical_name = "executive_summary"`, `trust = "agent_output"`,
`mime_type = "text/markdown"`). Its **producer is the CAB-2 gate card**, so it
becomes that card's `latest_artifact`.
- The rail's "Executive summary" slot maps to `decomposition_gate`.
  `decomposition_gate` is removed from the "Technical analysis" slot and
  `estimation` is added there.
- The action banner offers "Read executive summary" for an
  `approve_decomposition` ask, and opens the existing artifact dialog on the
  gate's `latest_artifact`.

**Why**: this uses no new DTO field. A gate card otherwise has no artifact of
its own, because the decomposition gate is resolved without a free-text answer,
so `latest_artifact` is exactly the summary. The dialog already shows the
`agent_output` trust chip (FR-013).

**Rejected**:
- Exposing `target_artifact_id` on `WorkCardGateOut`: that is another DTO
  field, and it points at JSON, not at readable prose.
- Making the decomposition card the producer, as #52 literally says ("off the
  decomposition card"): that card already carries `report` and
  `decomposition_candidate` with the same revision, and `latest_artifact`
  ordering among them is arbitrary. The intent of #52 (the summary is attached
  where CAB-2 is decided) is met.

## R4. Validation strictness: new output vs legacy candidates

**Decision**: There are two parse modes over one parser.
- **Strict** is used when routing a fresh pm result. It requires
  `classification` on every task, a non-empty `summary`, and unique
  `task_node_id`s. Missing ids are assigned deterministically as `t1…tn` in
  list order, but only if *no* task has an id. With partial ids, a task
  without one gets `t<index>`, and a collision with an existing id makes the
  result invalid.
- **Lenient** is used at publish time, on the gate target. Missing
  `classification` means `coding`, and a missing `estimate` means no estimate
  section (FR-019).

Both modes also add the type checks the current parser lacks: title and body
must be strings, and prerequisites a list of strings. Today a string
prerequisite is split into its characters.

**Why**: a gate opened before this feature must still publish (spec edge
case), but new output must never silently default a task to "agent-eligible".
Defaulting to coding would defeat #51.

## R5. Estimation output contract

**Decision**: The output is
`<ESTIMATES>{"estimates": [{task_node_id, size, confidence, man_hours,
agent_tokens, review_hours, risks, rationale}]}</ESTIMATES>`.
- Numbers: `man_hours` and `review_hours` are non-negative decimals.
  `agent_tokens` is a non-negative integer.
- `size` is one of `S M L XL`. `confidence` is one of `low medium high`.
- `risks` is a list of short strings. It may be empty; each entry is trimmed
  and deduplicated.
- `rationale` is a non-empty single line, trimmed. Newlines are collapsed to
  spaces rather than rejected.
- Cross-checks against the candidate: exactly one estimate per `task_node_id`,
  none unknown, none missing, and the FR-008 rules on positive and zero
  values.

The full contract is in `contracts/estimation-output.md`.

**Why**: this is the same tagged-JSON convention every other structured
specialist result uses (`<DECOMPOSITION>`, `<PRD>`, `<REFINEMENT_QUESTIONS>`),
and `extract_tag` already handles the trailing `<RESULT>` instruction in the
envelope.

## R6. Failure handling

**Decision**: An invalid estimation result creates a `coordinator_review` card
titled "Invalid estimates on card {id}: {reason}". The trigger key
`estimation:{card_id}:{attempt}` makes it idempotent per attempt. No gate is
created, which mirrors `route_decomposition_result`.

A **second gate guard** applies: if the workflow already has a
`decomposition_gate` in `awaiting_human`, estimation routing creates no new
gate and escalates. This is the spec's "never two CAB-2 gates" edge case,
which an operator retry of an estimation card could otherwise hit.

## R7. Manual tasks: the guard

**Decision**: A new content-free marker `ManualTaskSentinel`
(`<!-- kestrel:manual -->`) is added next to `SubtaskSentinel` in
`app/markers.py`, with `has_manual_sentinel(body)` in `task_source_utils.py`.
- Publishing applies it to manual tasks, in addition to `SubtaskSentinel`.
- `IngestionService._start_via_board` checks it right after the canonical
  fetch and before screening. It logs `ingest outcome=skipped-manual` and
  returns `None`.
- The child link is still recorded, so reset/cleanup still owns the published
  sub-task (constitution: cleanup only touches recorded, Kestrel-created
  artifacts).

**Why**: task-source adapters already apply any marker generically, including
Jira's code-span form, so no adapter changes. The check sits on the one path
that creates a workflow, so nothing downstream can ever claim a manual task
(FR-018).

**Cost accepted**: a manual sub-task is re-fetched on each poll that sees it,
because it never gets a run record. For a single-user tool with a handful of
manual tasks this is negligible. The #54 rework removes child tickets for
coding work anyway.

**Rejected**:
- Not publishing manual tasks at all: the human would then have no ticket to
  work from, and #51 says they are assigned to a human.
- A `manual` column on `child_task_link`: this needs a migration, and the
  marker is the source of truth that a human can see in the ticket.

## R8. Coordinator must not create estimation cards

**Decision**: `estimation` is excluded from the kinds a coordinator may
propose, joining the rule that already exists for kinds that need
code-created context. An estimation card is only ever created by decomposition
routing.

**Why**: an estimation card without a dependency edge to a candidate can only
fail. Letting the LLM create one is a pure error path.

## R9. Routing dispatch-branch budget

**Decision**: `_route_result` in `dispatch_ready.py` is already a chain of
`elif` branches near the branch limit (12). The four "coordinator and gates"
routes, plus the new estimation route, move into a kind-to-router mapping.
Verification keeps its own branch (async, best-effort).

**Why**: one more `elif` would breach the ruff/pylint branch limit, and
suppressions are forbidden. A table is also the more honest shape: every one
of these routes has the same signature.

## R10. Original request (FR-020–FR-023)

**Decision**:
- Backend: `BoardSnapshotOut.task_body: str = ""`, filled from
  `workflow.task_body`. `WorkflowSummaryOut` is not touched.
- Frontend: `BoardSnapshot.task_body: string`, changed in the same commit.
- `railItems(cards, taskBody)`: the `request` slot becomes a *direct-content*
  slot, available when `taskBody.trim() !== ''`.
- `ArtifactDialog` gains a second mode. Given `directContent` (plus a
  `note`), it does no fetch and shows no trust chip, only a `v-alert`
  freshness note. The content is still rendered as text through
  interpolation (FR-015 safety).

**Rejected**: a sibling `RequestDialog` component. It would copy the dialog
shell (title, divider, `<pre>`, actions) almost line for line, which jscpd
would flag.

## R11. Phase projection

**Decision**: add `CardKind.ESTIMATION` to phase 7 ("Technical analysis") in
`phases.py`. Nothing else changes (FR-025). The frontend mirrors phase *names*
only, so it needs no change there.

## R12. Out-of-scope follow-up issue

The actual-usage capture (record `session_id` on the attempt, and extract
`usage` and `total_cost_usd` from the backend's result event) and an
estimate-vs-actual view are filed as a new GitHub issue under epic #39 when
this feature lands. The research findings are already written up in Vikunja
707's comments and in this feature's tasks.md.

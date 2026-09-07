# Phase 0 Research: Task Decomposition Pipeline

Each item: **Decision**, **Rationale**, **Alternatives considered**.

## R1. New step names: reuse the dormant `describe`/`gap_analysis` slots

**Decision**: Name the new steps `Step.DESCRIBE = "describe"` (the
understanding-checkpoint) and `Step.GAP_ANALYSIS = "gap_analysis"` (the
technical-analysis phase), inserted into `Step.sequence()`
(`backend/app/models_workflow.py`) as `[DESCRIBE, REFINE, GAP_ANALYSIS,
DESIGN, CODE, VERIFY]`.

**Rationale**: `backend/app/policy.py` already carries `"gap_analysis"`,
`"clarify"`, and `"describe"` as fully-wired keys in both `DEFAULT_MODELS`
and `STEP_REQUIREMENTS`, but nothing in the codebase references them
(`grep` confirms zero other hits) — dormant scaffolding from an earlier,
unbuilt plan. `"describe"` and `"gap_analysis"` map cleanly onto this
feature's two new steps; reusing them costs nothing (a model default and a
capability requirement are already correctly declared: both are
`Capability.TEXT`-only, matching `refine`/`design`) and resolves otherwise
unexplained dead configuration instead of adding a third, parallel naming
scheme next to it.

**Alternatives considered**: Inventing fresh names (e.g. `assessment`,
`decompose`) — rejected, since it leaves the existing dormant entries as
unexplained debris while duplicating equivalent config; also considered
folding `describe` functionality into `refine` itself as a "round zero" —
rejected because `refine`'s gate/interview machinery is specifically
question-asking, while the understanding-checkpoint is a single
restate-and-confirm round with no questions, a materially different shape
better modelled as its own step. `"clarify"` is left unused; it does not
correspond to anything in this feature (refine already owns clarification)
and removing dead config is out of this feature's scope.

## R2. Pipeline shape: two gates, three gateless phases

**Decision**: `describe` (new gate `awaiting_describe_approval`) → `refine`
(existing gate `awaiting_refine_approval`, now altitude-scoped, see R7) →
`gap_analysis` (new, gateless, terminal on success) → `design` → `code` →
`verify` → `deliver`, exactly as today, but **only reachable for a run that
did not terminate at `gap_analysis`**.

**Rationale**: Confirmed directly with the requester: the parent run
terminates once `gap_analysis` publishes its output; a promoted follow-up
task skips `describe`/`refine`/`gap_analysis` entirely and starts at
`design`. Two human gates (describe, refine) plus one new gateless,
run-terminating phase composes cleanly with the existing `_TRANSIENT`/gate
machinery (`backend/app/services/workflows/gate.py`,
`backend/app/services/workflows/shared.py`) without altering their
generic contracts (see R8).

**Alternatives considered**: A single merged "describe-and-refine" gate —
rejected per the requester's explicit two-step ask (restate first, PRD
second) and because a restatement and a go/no-go PRD answer different
questions ("did I understand you" vs. "should this happen"). A gate on
`gap_analysis` too — not requested; kept gateless to match `design`'s
existing autonomy and avoid a three-approval pipeline the requester did not
ask for (documented as an assumption in `spec.md`).

## R3. Follow-up task creation: one new `TaskSource` method, source-specific bodies

**Decision**: Add `async def create_subtask(self, parent_ref: str, title:
str, body: str) -> str` to the `TaskSource` protocol
(`backend/app/ports.py`), required (not optional) on every implementation:

- **GitHub** (`backend/app/services/github.py`): create a new issue in the
  same repository via the existing `GitHubClient` (a `create_issue`
  method needs adding — today's client only reads/comments/labels), body
  prefixed with a `Sub-task of #<parent-number>` reference line. Created
  **without** the source's configured `trigger_label`.
- **Jira** (`backend/app/services/jira.py`): create a native `Sub-task`
  issue type linked to the parent via Jira's own parent-issue field (the
  idiomatic Jira subdivision, distinct from a plain linked issue) via
  `JiraClient` (needs a `create_issue`/`create_subtask` method).
- **Fixture** (`backend/app/services/fixture.py`): write a new JSON task
  file under the same `fixtures_dir`, with a `parent` field pointing at
  the originating file's ref — mirroring how a real sub-task would carry
  parent linkage, cheaply, for local testing.

**Rationale**: `TaskSource` is already the seam for "does something to the
ticket" (`post_comment`, `attach`, `publish_refined`); a new capability
belongs there, not in a parallel port. Matches the existing per-source
adapter pattern (`services/{github,jira,fixture}.py`) exactly. Making it
required (not a default-no-op) matches FR-009/FR-011 in `spec.md`:
decomposition is unconditional, so every source must support it — there is
no "source can't do this" branch to design around (edge case in `spec.md`
explicitly rules this out).

**Alternatives considered**: A generic "create linked ticket" abstraction
shared with `attach`/`post_comment` — rejected; the three sources' native
"this is a subdivision" concepts are different enough (GitHub has no
native sub-issue type at the API layer used here, Jira has one, fixture is
synthetic) that a single generic call would leak provider detail through
an awkward parameter, not hide it.

## R4. No accidental re-trigger: omit the trigger condition at creation time

**Decision**: A created follow-up task must not satisfy its source's
ingestion-trigger condition at creation time — GitHub: created without
`trigger_label`; Jira: the operator's `jql` is documented (in
`docs/setup-jira-workflow.md`, alongside existing operator warnings such as
the `hooks_dir` trust-boundary note) to exclude newly created sub-tasks by
default scoping (e.g. matching on the trigger label/status the JQL already
keys off), the same way the project already puts a documentation-only
burden on the operator for other source-specific risks rather than
mechanically enforcing everything in code.

**Rationale**: `backend/app/routers/github_webhook.py` only reacts to a
`labeled` action on the configured `trigger_label`;
`backend/app/services/reconcile.py` re-lists by that same label;
`backend/app/services/jira_poll.py` re-runs the operator's configured
`jql`. None of the three inspects ticket body content before deciding
whether a ticket qualifies, and `IngestionService.maybe_start_run`
(`backend/app/services/ingestion.py`) is only ever called once a trigger
has already decided a ticket qualifies — so the only point that can
prevent an unwanted run is not satisfying the trigger condition in the
first place. This is consistent with the project's existing risk posture
(e.g. the `hooks_dir` secret-equivalent trust boundary, constitution
v1.4.0, is a documented operator responsibility with a startup audit-log
nudge, not a mechanically enforced control) rather than introducing a new,
heavier suppression mechanism the requester did not ask for.

**Alternatives considered**: A new "pending promotion" suppression store
(parallel to `DismissalStore`) that blocks ingestion for any known
follow-up `task_ref` until an explicit "promote" action — rejected: the
requester's own example ("a human applies the trigger label to it") is
exactly today's existing ingestion gesture, so building a second,
parallel promotion mechanism would be speculative generality (Constitution
IV) the requester did not ask for and that duplicates a control the
label/JQL gate already provides everywhere else in the system.

## R5. Fast path for a promoted follow-up task: extend the sentinel convention

**Decision**: Extend `backend/app/services/workflow_text.py`'s existing
sentinel mechanism (`SENTINEL = "<!-- kestrel:refined -->"`,
`has_sentinel`/`append_sentinel`, consumed today only in
`driver.drive()`: `if has_sentinel(task.body): run.steps[0].status =
"done"; ...`) with a second, distinct sentinel meaning "this ticket is
already a scoped, self-contained follow-up task — skip straight to
`design`." `create_subtask`'s body includes it. `driver.drive()` gains a
second branch: on the new sentinel, pre-mark `describe`, `refine`, and
`gap_analysis` steps `"done"` (their `deliverable` left empty/marked, since
nothing produced them) and seed the step immediately consumed by `design`
(today `run.steps[0].deliverable`, see R6) with the fetched task body
itself — the self-contained follow-up content is what `design` designs
from.

**Rationale**: This is the same mechanism the codebase already uses to let
a ticket skip `refine` when its body is already a finished PRD — the
follow-up-task fast path is the identical shape one level further down the
pipeline, so extending it (a second sentinel constant, a second branch in
one function) is smaller and more consistent than inventing a new
run-creation parameter or a new WorkflowRun field to carry "start step".

**Alternatives considered**: A `WorkflowService.create(..., start_step=...)`
parameter — rejected: it would need to reach every caller (webhook,
reconcile, Jira poll, fixture poll) with a way to know a ticket is a
follow-up *before* fetching its body, which none of them currently do (they
only know a ref); the sentinel-in-body approach needs no caller change at
all, since `drive()` already fetches the body first and branches on it.

## R6. `design`'s PRD input, generalized

**Decision**: `driver.design()` (`backend/app/services/workflows/driver/
__init__.py`) currently reads `run.steps[0].deliverable` (the `refine`
step) as `prd`. With `describe` now at index 0, `refine` moves to index 1;
`design` must read `run.steps[1].deliverable` instead. For a fast-pathed
follow-up run (R5), that same index is seeded directly with the follow-up
task's own body, so `design`'s code needs no branch on *how* it got there.

**Rationale**: Keeps `design()` ignorant of whether it's designing from a
normal `refine` output or a fast-pathed follow-up body — the existing
"read the step before me" contract is preserved, just re-indexed, matching
Constitution II's "downward-only calls" and avoiding a new conditional in
an already-gateless, already-simple function.

## R7. Altitude-scoped profile selection per phase

**Decision**: `refine`'s coordinator (`COORDINATOR_PROMPT`,
`backend/app/services/workflows/prompts.py`) and its profile roster
(`backend/app/profiles.py`) are restricted, when reached via this
pipeline, to non-technical/requestor-altitude profiles only (`requester`,
`pm`, `uiux`, framed at business altitude — never `developer`, `infosec`,
`dba`, `architect`, `ops`). Concretely: the `COORDINATOR_PROMPT` and
`GENERATION_PROMPT` used at the `refine` step are given a **restricted
roster view** (a business-altitude subset of `roster_summary()`), not the
full roster; `gap_analysis` instead uses a **technical-altitude roster
view** (`developer`, `infosec`, `dba`, `architect`, `ops`, `qa`) with each
profile's existing `system_prompt` reused as-is (already technical by
construction) plus a phase framing that asks each profile to analyze and
decide, not interview a human.

**Rationale**: The requester was explicit: profile *identity* may overlap
between phases, but altitude must differ per phase. Since `refine`'s
profiles already lean toward one altitude by content (`requester` is
already told to "avoid implementation detail"), the *cheapest* correct
change is restricting which profiles `refine`'s coordinator is even shown
(a filtered `roster_summary()` argument), not building a second, parallel
prompt-fragment system on `Profile` itself.

**Alternatives considered**: Adding an `altitude: Literal["business",
"technical"]` field to `Profile` and filtering the roster by it inside
`coordinator_profiles` — a reasonable alternative with the same effect,
slightly more self-documenting at the cost of a schema field on every
roster entry; left as an implementation-phase choice between the two
(functionally equivalent, `/speckit-tasks` picks one), not a spec-level
decision.

## R8. Technical-analysis phase shape: reuse the interview round shape, un-gated

**Decision**: `gap_analysis` (`backend/app/services/workflows/driver/
__init__.py`, new `gap_analysis()` function alongside `design()`) reuses
the proven **fan-out → reconcile → critic** shape already implemented for
`refine` (`backend/app/services/workflows/interview/questions.py`:
`generate_questions`/`reconcile_questions`/`critique_coverage`), but
analysis-flavored instead of question-flavored: each technical profile
contributes proposed architecture decisions and task-breakdown candidates
in parallel; a writer/reconciler turn merges them into the
technical-analysis document plus the follow-up task list; a **completeness
self-review turn**, structurally identical to `critique_coverage`, checks
each follow-up task against the self-containment requirement (spec.md
FR-010) before anything is published — mirroring how `critique_coverage`
today checks that no stakeholder's concern was lost in the interview fold.

**Rationale**: This is an autonomous (gateless) step, so there is no human
to catch an incomplete follow-up task the way a human catches a bad
questionnaire fold — the self-review turn is what stands in for that
missing human check, directly answering the sanity check raised for this
feature ("does the task source contain everything needed to implement the
full work package in total isolation, even for a human?").

## R9. New terminal run status: `decomposed`

**Decision**: `gap_analysis` completing successfully sets `run.status =
"decomposed"` (a new terminal status, alongside existing `done` / `failed`
/ `rejected` / `escalated`), and `continue_run()`
(`backend/app/services/workflows/driver/__init__.py`) gains an early
return after `gap_analysis`, mirroring the existing `if escalated: return`
short-circuit after `code_and_verify`.

**Rationale**: `done` today specifically means "a change request was
opened" (`deliver()` sets it after pushing/opening the PR/MR); reusing it
for "decomposed into follow-up tasks, nothing was implemented" would make
`done` ambiguous to both the UI and any future reader of run history. A
distinct terminal status costs nothing (status is a free-form string
column, no migration — see `data-model.md`) and matches the existing
pattern of one status per distinct terminal outcome (`escalated` is the
precedent: also success-adjacent-but-distinct from `done`).

## R10. No new persistence

**Decision**: No new `WorkflowRun`/`WorkflowStep` database column and no
new Alembic migration are needed. `describe`'s and `gap_analysis`'s
per-step `deliverable` (already a `Text` column on `workflow_step`) holds
the understanding statement and the technical-analysis document text
respectively, exactly as `refine`/`design` already store their output
there. The list of follow-up tasks created by `gap_analysis` is not
persisted by kestrel at all — the requester's own confirmed decision (the
parent run ends immediately after `gap_analysis`) means nothing downstream
in kestrel ever needs to re-read that list; it is fully recorded instead in
the published technical-analysis document and in each follow-up ticket's
own body (FR-011/FR-012), consistent with the project's existing posture
that the task source, not kestrel's database, is authoritative for ticket
relationships.

**Rationale**: Constitution IV (Deliberate Simplicity): a migration adding
a column that nothing ever reads back is pure cost. `WorkflowStepRow`
(`backend/app/persistence/tables.py`) is keyed by `(workflow_id,
position)` with a free-form `name`, so extending `Step.sequence()` from
four to six entries needs no schema change either — new runs simply get
six `WorkflowStepRow`s instead of four, the same way feature 003 added
`verify` with no migration beyond the columns it actually needed.

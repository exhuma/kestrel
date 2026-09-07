# Phase 1 Data Model: Task Decomposition Pipeline

No new database table or column is introduced (see `research.md` R10). This
document maps the spec's Key Entities onto existing structures, extended in
place, plus the one new run-status/step-name vocabulary addition.

## `Step` (enum, `backend/app/models_workflow.py`)

Extended from four to six members, in pipeline order:

```python
class Step(StrEnum):
    DESCRIBE = "describe"        # NEW
    REFINE = "refine"
    GAP_ANALYSIS = "gap_analysis"  # NEW
    DESIGN = "design"
    CODE = "code"
    VERIFY = "verify"
```

`Step.sequence()` returns all six, in this order. `WorkflowService.create()`
already builds `run.steps` from `Step.sequence()`
(`WorkflowStep(name=step) for step in Step.sequence()`), so every new run
automatically gets six `WorkflowStep`/`WorkflowStepRow` entries with no
further change at the persistence layer (positions 0-5).

## `WorkflowStep` (dataclass, unchanged shape)

Reused as-is for both new steps — no new field:

| Step | `deliverable` holds | Gate? |
|---|---|---|
| `describe` (idx 0) | The **Understanding Statement**: kestrel's plain-language restatement of the task, revised in place across amendment rounds (same shape as `refine`'s reject-with-feedback rewrite) | Yes — `awaiting_describe_approval` |
| `refine` (idx 1) | The **Requirements Document** (today's "PRD"), now altitude-restricted to non-technical content (research.md R7) | Yes — `awaiting_refine_approval` (existing gate, unchanged mechanics) |
| `gap_analysis` (idx 2) | The **Technical-Analysis Summary**: architecture/technical decisions and rationale (the follow-up task list itself is not persisted here — research.md R10) | No — gateless, run-terminating on success |
| `design` (idx 3) | Unchanged: the technical design/plan, now read from `run.steps[1].deliverable` (refine) on a normal run, or seeded directly from a follow-up task's own body on a fast-pathed run (research.md R5/R6) | No |
| `code` (idx 4) | Unchanged | No |
| `verify` (idx 5) | Unchanged | No |

## `WorkflowRun` (dataclass, unchanged shape)

No new field. `status` (already a free-form string, no DB enum
constraint — `persistence/tables.py::WorkflowRunRow.status`) gains new
values:

- `"describing"` — `describe` step running (mirrors `"refining"`).
- `"awaiting_describe_approval"` — the new gate (mirrors
  `"awaiting_refine_approval"`; both end in `_approval`, so the existing
  generic `gate.py::resolve()` check `run.status.endswith("_approval")`
  already accepts it with no code change there).
- `"analyzing"` — `gap_analysis` step running.
- `"decomposed"` — new terminal status: `gap_analysis` published its
  output successfully and the run ended without proceeding to `design`
  (research.md R9).

`_TRANSIENT` (`backend/app/services/workflows/shared.py`) gains
`"describing"` and `"analyzing"` (fail loudly on restart, same as
`"refining"`/`"designing"`); `"decomposed"` joins the terminal set
(`"done"`/`"failed"`/`"rejected"`/`"escalated"`) wherever that set is
enumerated (e.g. any UI status-to-color/label map).

## `Task` / `TaskSource` (`backend/app/ports.py`)

`TaskSource` protocol gains one new required method:

```python
async def create_subtask(
    self, parent_ref: str, title: str, body: str
) -> str:
    """Create a follow-up task linked to parent_ref; return its new ref."""
    ...
```

No new dataclass. A **Follow-up Task** (spec.md Key Entity) is not a new
kestrel type — it is a `Task` (existing dataclass: `ref`/`title`/`body`)
whose `body` is fully self-contained (spec.md FR-010) and whose linkage to
its parent lives in the underlying source (a reference line in a GitHub
issue body, a native Jira parent field, a `parent` field in a fixture JSON
file — research.md R3), not in any kestrel-owned structure.

## Sentinel vocabulary (`backend/app/services/workflow_text.py`)

One new sentinel constant alongside the existing `SENTINEL =
"<!-- kestrel:refined -->"`:

```python
SUBTASK_SENTINEL = "<!-- kestrel:subtask -->"
```

`has_subtask_sentinel(body)` / the existing `has_sentinel`-style helper
pair. Written into a follow-up task's body by `create_subtask` callers
(`gap_analysis()`), read by `driver.drive()` to select the fast path
(research.md R5).

## Validation rules (from spec.md Functional Requirements)

- FR-002/FR-003: `describe` cannot leave `awaiting_describe_approval` for
  `refine` without an explicit approve decision (enforced the same way
  `refine`'s existing `_Rejected`/loop-until-approved shape already
  enforces FR-006/FR-007 for `awaiting_refine_approval`).
- FR-004/FR-005: `refine`'s coordinator, when reached through this
  pipeline, is only ever given the business-altitude roster subset
  (research.md R7) — enforced in code (which roster view is passed in),
  not by prompt instruction alone.
- FR-009: `gap_analysis` MUST produce at least one follow-up task even for
  an indivisible approved requirements document — enforced by the
  synthesis/writer turn's output contract (`contracts/gap-analysis-output.
  md`), checked before publishing.
- FR-010: every follow-up task's self-containment is checked by the
  completeness self-review turn (research.md R8) before `create_subtask`
  is ever called for it.
- FR-013: `create_subtask` implementations MUST NOT cause the created
  ticket to satisfy its source's ingestion-trigger condition (research.md
  R4) — a contract obligation on each `TaskSource` implementation, not
  something enforced by a shared code path (there is none to share across
  three structurally different trigger mechanisms).

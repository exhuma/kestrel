# Contract: `gap_analysis` step output

The gateless, run-terminating step that turns an approved, business-altitude
requirements document into a technical-analysis summary and a set of
follow-up tasks (spec.md User Story 3).

## Inputs

- The approved Requirements Document (`run.steps[1].deliverable`, per
  `data-model.md`).
- The original ticket's confirmed Understanding Statement
  (`run.steps[0].deliverable`) and the underlying codebase — same
  read-the-repo access `design`/`refine`'s specialists already have.

## Output (before anything is published)

1. **Technical-Analysis Summary** (`run.steps[2].deliverable`): the
   architecture/technical decisions made and their rationale (spec.md
   FR-008). Written as a `.kestrel/<date>-<serial>/` artifact
   (`technical-analysis.md`) via the existing `artifacts.py` handover
   pattern (`ensure_artifact_dir`/`write_artifact`), same as
   `prd.md`/`design.md`.
2. **One or more follow-up tasks** (spec.md FR-008/FR-009): each a
   `(title, body)` pair. **Never zero** — a work item judged indivisible
   still yields exactly one follow-up task (re-scoped technically), so
   "the run always ends by publishing at least one follow-up task" holds
   even in the degenerate case (spec.md FR-009).

## Self-containment gate (spec.md FR-010) — MUST run before publishing

A completeness self-review turn (research.md R8, structurally mirroring
`interview/questions.py::critique_coverage`) checks **each** candidate
follow-up task against this question, framed exactly as it was raised for
this feature: *if a human with no access to the parent ticket, the
requirements document, the technical-analysis summary, or any sibling
follow-up task read only this task's body, could they implement it in
total isolation?*

A task that fails this check is **not** published as-is — it is revised
(the relevant architecture decision, shared interface/contract detail, or
acceptance criterion it was missing is inlined into it) and re-checked.
This mirrors `critique_coverage`'s existing role: catching a real gap
introduced by consolidation, not nitpicking wording.

## Publishing (only after the self-containment gate passes for every task)

1. Each follow-up task is created via `TaskSource.create_subtask`
   (`contracts/task-source-subtask-port.md`) — body carries
   `SUBTASK_SENTINEL` and the self-contained content, title referencing
   the parent (spec.md FR-011).
2. The Technical-Analysis Summary is published back to the **original**
   ticket via the existing `attach`/`publish_refined`-style mechanism
   (source-appropriate — Jira attaches, GitHub updates/comments), for
   human reference (spec.md FR-012).
3. `run.status = "decomposed"`; the run ends (spec.md FR-014) — no
   `design`/`code`/`verify` on the original ticket.

## Failure handling

A failure anywhere in this step (a technical profile's turn erroring, a
`create_subtask` call failing after the self-containment gate passed) is
**not** silently swallowed: it fails the run (`run.status = "failed"`),
exactly like any other unhandled exception during a gateless step today
(`driver.drive()`'s existing top-level `except Exception` handling) — a
partially-published decomposition is a real failure to surface, not a
best-effort operation like a post-hoc comment.

## Test contract

- An approved requirements document judged indivisible still yields
  exactly one published follow-up task plus a technical-analysis summary.
- The technical-analysis summary is published back to the **original**
  ticket (spec.md FR-012) — not merely written to the worktree artifact —
  distinct from the follow-up tasks published via `create_subtask`.
- A follow-up task that initially fails the self-containment check is
  revised and re-checked before publishing — never published on first
  failure.
- `gap_analysis` completing successfully always results in `run.status ==
  "decomposed"`, never `"designing"`.
- A `create_subtask` failure after the self-containment gate passed fails
  the run rather than silently publishing a partial set.

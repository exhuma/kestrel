# Quickstart: validating the task decomposition pipeline

Uses the **fixture** task source (`backend/app/services/fixture.py`,
feature 008) — file-backed, no real GitHub/Jira ticket needed — the same
tool the project already uses for disposable local runs.

## Prerequisites

- `config.toml` has a `[[task_sources]]` entry with `type = "fixture"` and
  a `fixtures_dir` (see `config.toml.example`).
- Backend running from source (`uv run ...` per `docs/`) with a `claude`
  CLI login available, or `KESTREL_WORKFLOW_DEBUG=1` if inspecting the
  worktree after a run matters for this check.

## Scenario 1 — understanding checkpoint (US1)

1. Write a fixture task file under the configured `fixtures_dir` whose
   body is deliberately ambiguous (e.g. names a feature without saying
   which of two plausible interpretations is meant).
2. Start a run against it (fixture ingestion, per existing feature-008
   convention).
3. **Expect**: the run parks at `awaiting_describe_approval` before any
   interview question is asked (spec.md SC-001). The step's restatement
   text should name the ambiguity in plain language.
4. Submit a correction via the reject-with-feedback path (existing
   `/reject` endpoint with `refinement` text set — same shape `refine`'s
   gate already accepts).
5. **Expect**: a revised restatement incorporating the correction, run
   re-parked at `awaiting_describe_approval`.
6. Approve.
7. **Expect**: run proceeds into `refining`.

## Scenario 2 — non-technical, go/no-go requirements document (US2)

Continuing from Scenario 1:

1. Answer the interview questions the coordinator raises.
2. **Expect**: every question asked is phrased at business/requestor
   altitude — none probes implementation approach, architecture, or
   technical feasibility (spot-check against spec.md FR-004).
3. **Expect**: the resulting document at `awaiting_refine_approval`
   contains no implementation/architecture language (spec.md FR-005,
   SC-002).
4. Reject with feedback once; confirm a revised document is produced and
   re-parked. Then approve.
5. **Expect**: run proceeds into `analyzing`.

## Scenario 3 — technical analysis and decomposition (US3)

Continuing from Scenario 2, using a task deliberately scoped to require
more than one follow-up task (e.g. touches both a data model and a
user-facing surface):

1. Wait for `gap_analysis` to complete.
2. **Expect**: `run.status == "decomposed"`; the run does **not** reach
   `designing` (spec.md SC-006).
3. **Expect**: two or more new fixture task files appear in `fixtures_dir`,
   each referencing the original task's ref, each body containing
   `SUBTASK_SENTINEL`.
4. **Expect**: each new fixture task's body, read on its own with no other
   file open, is sufficient to understand what to build — no unresolved
   reference to "see the technical analysis" or "see task N" for
   information the task itself needs (spec.md FR-010, SC-003 / the
   self-containment sanity check).
5. **Expect**: a `technical-analysis.md` artifact exists under
   `.kestrel/<date>-<serial>/` in the run's (now torn-down) worktree
   history, or — if `KESTREL_WORKFLOW_DEBUG=1` — inspect it directly
   before teardown.
6. **Expect**: no new run was auto-started for either new fixture task as
   a side effect of their creation (spec.md FR-013, SC-004) — check the
   workflow list; only the original (now `decomposed`) run should exist.

## Scenario 4 — follow-up task fast path (US3, end of story)

1. Manually trigger ingestion for one of the follow-up fixture tasks
   created in Scenario 3 (the same deliberate action a human takes to
   promote any fixture task today).
2. **Expect**: the new run skips `describing`/`refining`/`analyzing`
   entirely and starts at `designing` (spec.md SC-005) — no
   understanding-checkpoint or requirements-document prompt appears for it.
3. Let it run to completion (`design` → `code` → `verify` → `deliver`) or
   stop once `designing` is confirmed reached, per what's being validated.

## Regression check

Run an ordinary task through the pipeline end-to-end (all four scenarios
combined is the full path) and confirm the existing `code`/`verify`/
`deliver` behavior (feature 003/005/006) is unaffected — this feature only
inserts steps before `design`, it does not touch anything from `design`
onward except the PRD-input re-indexing (research.md R6).

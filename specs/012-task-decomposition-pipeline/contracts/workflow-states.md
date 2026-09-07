# Contract: extended workflow state machine

Extends `.specify/specs/003-jira-ingestion/contracts/workflow-states.md`
(the current authoritative contract) with two new steps and one new
terminal status. Every run — GitHub, Jira, fixture — still traverses the
identical state sequence; only the bound `TaskSource`/`CodeHost` and the
notification surface vary (unchanged principle from feature 003).

## Steps

`["describe", "refine", "gap_analysis", "design", "code", "verify"]` — the
first three are new/renamed relative to today's `["refine", "design",
"code", "verify"]`; `design`/`code`/`verify` are otherwise unchanged.

## Run statuses — normal (non-fast-pathed) run

```text
pending ─► cloning ─► describing ─► awaiting_describe_approval   ← NEW gate (understanding)
                                       │ approve            │ reject w/ feedback   │ reject, no feedback
                                       ▼                    ▼                      ▼
                                    refining          (revise, re-park)         rejected
                                       │
                          ┌────────────┴──────────────┐
                          ▼                            │
              awaiting_refine_input ──(answers)─────────┘
                          │
                          ▼
              awaiting_refine_approval   ← EXISTING gate, now altitude-scoped (business PRD)
                 │ approve            │ reject w/ feedback   │ reject, no feedback
                 ▼                    ▼                      ▼
              analyzing         (revise, re-park)          rejected
                 │
                 ▼ (gateless, autonomous)
             decomposed   ← NEW terminal status; run ends here (FR-014)
```

## Run statuses — fast-pathed follow-up-task run

```text
pending ─► cloning ─► (body carries SUBTASK_SENTINEL) ─► designing ─► coding ─► verifying ─► opening_pr ─► done
```

`describe`, `refine`, `gap_analysis` steps are pre-marked `"done"` at
`drive()` time (research.md R5); the run enters `continue_run()` with
`run.steps[0..2].status == "done"` already true, so it falls straight
through to `design` exactly the way today's `has_sentinel` shortcut falls
straight through `refine` alone.

## Gates

- `awaiting_describe_approval` (NEW): the human confirms or amends
  kestrel's restated understanding. Reuses `_Control`/`_Decision`/
  `await_gate`/`resolve` (`backend/app/services/workflows/gate.py`)
  unchanged — `resolve()`'s `run.status.endswith("_approval")` check
  already accepts this status with no code change.
- `awaiting_refine_approval` (EXISTING, unchanged mechanics): now reached
  only with a business-altitude-restricted coordinator/roster (research.md
  R7); still the PRD/go-no-go gate.
- `gap_analysis` is gateless (matches `design`/`code`/`verify`'s existing
  autonomy) — see spec.md Assumptions for why no second technical-review
  gate was added.

## `_TRANSIENT` (fail loudly on restart)

Adds `"describing"`, `"analyzing"` to the existing set (`"pending"`,
`"cloning"`, `"refining"`, `"designing"`, `"coding"`, `"verifying"`,
`"opening_pr"`).

## Terminal statuses

Adds `"decomposed"` to the existing set (`"done"`, `"failed"`,
`"rejected"`, `"escalated"`).

## Test contract (extends feature 003's)

- A run that never gets a `SUBTASK_SENTINEL` body always passes through
  `describe` and (altitude-scoped) `refine` before `gap_analysis` —
  regardless of source.
- `gap_analysis` completing successfully always yields `status ==
  "decomposed"` and the run never reaches `designing`.
- A run whose fetched task body carries `SUBTASK_SENTINEL` skips directly
  to `designing` with `describe`/`refine`/`gap_analysis` all `"done"` at
  the first save.
- Rejecting `awaiting_describe_approval` with no feedback ends the run
  `"rejected"` with a dismissal recorded — identical shape to today's
  `awaiting_refine_approval` no-feedback rejection.
- Restart during `"describing"`/`"analyzing"` → `"failed"` (transient);
  restart at `"awaiting_describe_approval"` → re-parked, no duplicate
  notification (same `recover()` contract as every other `awaiting_*`
  status).

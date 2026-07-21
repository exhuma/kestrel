# Contract: reshaped workflow state machine

The unified, source-agnostic pipeline (`services/workflows.py`). Every run — Jira, GitHub,
manual — traverses the same states and gates (FR-024). The task source changes only the bound
`TaskSource`/`CodeHost` and the notification surface, never the path (FR-026).

## Steps

`["refine", "design", "code", "verify"]` (renamed from `refine`/`plan`/`implement`; `verify`
is new). Step names are free-form persisted strings (`workflow_step.name`), so historical
`plan`/`implement` rows need no migration.

## Run statuses

```text
pending ─► cloning ─► refining ─┬─► awaiting_refine_input ──(answers)──┐
                                └──────────────────────────────────────┤
                                                                        ▼
                                                       awaiting_refine_approval   ← the ONE human gate (PRD)
                                                          │ approve            │ reject
                                                          ▼                    ▼
                          publish PRD to ticket        designing            rejected (dismissal written)
                                                          ▼
                                                        coding ◄────────────────┐
                                                          ▼                     │ reject & iterations remain
                                                       verifying ───────────────┘   (re-run coder w/ feedback)
                                                          │ accept        │ iterations exhausted
                                                          ▼               ▼
                                                      opening_pr       escalated  (thin RFC comment; terminal)
                                                          ▼
                                                         done
```

- **Gates** (`awaiting_*`, re-parked on restart by `recover()`): `awaiting_refine_input`
  (clarification — thin deep-link to the questionnaire, US2), `awaiting_refine_approval`
  (**PRD approval** — the only approval gate).
- **Gateless autonomous phases**: `designing`, `coding`, `verifying` (FR-014).
- **`_TRANSIENT`** (fail loudly on restart, `services/workflows.py:77`): `pending`, `cloning`,
  `refining`, `designing`, `coding`, `verifying`, `opening_pr`.
- **Terminal**: `done`, `failed`, `rejected`, **`escalated`**.

## Verify loop (FR-015, FR-015a, FR-016–FR-018, R-06 — see `contracts/verify-evidence.md`)

1. `code` produces a diff; an **evidence gatherer** produces `Evidence` (a list of
   `Observation`s). Design assumes behavioural exercise of the running project — HTTP requests
   for an API, Playwright for a GUI (`kind="http"`/`"ui"`); v1 ships a minimal `check` gatherer
   over `verify_checks`. Empty when nothing is gathered.
2. `verify` runs the `verifier` agent (in the worktree cwd) with `VERIFY_PROMPT` = PRD + design
   deliverable + diff + **evidence**; it adjudicates the observed behaviour against the PRD.
3. Verdict `<VERDICT>{"accept": bool, "feedback": str}</VERDICT>`. **Invariant**: any failing
   `Observation` forces a rejection regardless of the model text.
4. `accept` → `_deliver` (open change request, notify ticket with the link, `done`).
5. reject & `iterations < max_verify_iterations` → re-run `code` with feedback that **includes
   the failing observations** (`CODE_FEEDBACK` prompt pattern), increment the in-memory counter,
   re-verify.
6. reject & exhausted → `escalated`, post a thin escalation comment on the ticket, teardown.

## Gates & notifications

- Reuses `_await_gate`/`_Control`/`_resolve` (`services/workflows.py:566,628`); gateless phases
  simply never set an `awaiting_*` status.
- `_save` (`services/workflows.py:350`) stays the single persist+notify+publish choke point;
  every transition (including `escalated` and the `opening_pr`→`done` link post) flows through
  it, so the notifier can't be bypassed.
- Approval/answers arrive via the existing endpoints (`routers/workflows.py`:
  `approve`/`reject`/`submit_answers`/`save_draft`) reached through the deep-link — unchanged
  API surface, now feeding the unified workflow.

## Removed vs feature 002

Removed statuses: `planning`, `awaiting_plan_approval`, `implementing`,
`awaiting_implement_input`, `awaiting_implement_approval` (the mid-loop human gates). A blocked
coder no longer parks on `awaiting_implement_input`; inability to proceed autonomously fails the
run and escalates (FR-020).

## Test contract

- A Jira run and a GitHub run traverse the identical status sequence (differing only in bound
  source/host and notification surface) — FR-024.
- design/code/verify never set an `awaiting_*` status (no human gate) — FR-014.
- verifier accept → `opening_pr` → `done` with a change-request link on the ticket.
- verifier reject once → coder re-runs → accept → `done`.
- verifier reject to exhaustion → `escalated`, no change request, one escalation comment.
- restart during `coding`/`verifying` → `failed` (transient); restart at
  `awaiting_refine_approval` → re-parked, no duplicate comment.

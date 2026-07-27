# Phase 1 Data Model: Task-Source Lifecycle Sync, Time Tracking, and Operator Hooks

## `WorkflowRun` (extended) — `backend/app/models_workflow.py`

Persisted mirror: `WorkflowRunRow` — `backend/app/persistence/tables.py:46-83`.

| Field | Type | Default | Notes |
|---|---|---|---|
| `active_seconds` | `float` | `0.0` | Cumulative time the run has spent in the `"active"` clock state. Never decreases. Authoritative source for FR-005/FR-006's active-time metric. |
| `wait_seconds` | `float` | `0.0` | Cumulative time the run has spent in the `"waiting"` clock state (parked at `awaiting_refine_input`/`awaiting_refine_approval`). Never decreases. Authoritative source for FR-005's wait-time metric. |
| `clock_state` | `"active" \| "waiting" \| None` | `None` | Which clock is currently running. `None` before the run starts and after it reaches any terminal status. |
| `clock_since` | `datetime \| None` (naive UTC) | `None` | Timestamp `clock_state` last changed. `None` exactly when `clock_state` is `None`. |

**Invariant**: `clock_since is not None` if and only if `clock_state is not None`. Both
are written together, only by `_set_clock` (see below) — no other code path assigns
either field directly.

**State machine** (a run's clock, distinct from `run.status`):

```
        _set_clock(run, "active", now)          _set_clock(run, "waiting", now)
  None ─────────────────────────────► active ◄─────────────────────────────► waiting
   ▲                                     │                                       │
   └─────────────────────────────────────┴───────────────────────────────────────┘
                        _set_clock(run, None, now)   (terminal — from either state)
```

`_set_clock(run, state, now)` (new, `backend/app/services/time_tracking.py`):
1. If a clock is currently running (`clock_state is not None`), add
   `(now - clock_since).total_seconds()` to `active_seconds` if it was `"active"`,
   else to `wait_seconds`.
2. Set `clock_state = state`; `clock_since = now if state is not None else None`.

**Call sites in `backend/app/services/workflows.py`** (mechanical, enumerable):

| Transition | Site | Existing line (approx.) |
|---|---|---|
| `None → "active"` (run starts) | Right after `run.status = "cloning"` | `_drive`, ~1132 |
| `"active" → "waiting"` (enters a gate) | Each `awaiting_refine_input`/`awaiting_refine_approval` assignment | ~1224, 1246, 1341 |
| `"waiting" → "active"` (leaves a gate) | Gate resolution back into `run.status = "refining"` | `_refine`, ~1292 |
| `"active"\|"waiting" → None` (terminal) | Centralized in `_save()` — if `run.status in {"done","failed","rejected","escalated"}` and `clock_state is not None` | `_save`, `workflows.py:654-693` |

Centralizing the terminal transition inside `_save()` (rather than patching all ~7
terminal-status assignment sites individually) guarantees no terminal is ever missed
regardless of which status put the run there, and is naturally idempotent — a second
`_save()` call on an already-stopped run is a no-op (`clock_state` is already `None`).

`coding`/`verifying`/`opening_pr` and the code↔verify loop-back do **not** call
`_set_clock` — they're already inside an `"active"` span that started at
`cloning`/gate-resume.

## `LifecycleEvent` (new, transient) — `backend/app/ports.py`

Not persisted; constructed fresh for each dispatch and passed to
`TaskSource.transition()` and `HookRunner.run()`.

| Field | Type | Notes |
|---|---|---|
| `kind` | `"start" \| "done" \| "failed" \| "escalated" \| "rejected"` | Derived from `run.status` via a single exclusive mapping — see Invariant below. |
| `active_seconds` | `float \| None` | `run.active_seconds` at dispatch time. |
| `wait_seconds` | `float \| None` | `run.wait_seconds` at dispatch time. |
| `deep_link` | `str` | Reuses `gate_deep_link()` (`notifications.py:104-114`) — the kestrel UI deep-link to the run, when a public base URL is configured. |

**Invariant (tested, see `contracts/task-source-protocol.md`)**: `kind` is derived from
`run.status` via exactly one mapping (`done→"done"`, `failed→"failed"`,
`escalated→"escalated"`, `rejected→"rejected"`, first non-gate active status→`"start"`).
No code path can produce `kind="done"` for a run whose `run.status` is a failure
terminal.

## `TaskSourceConfig` (extended) — `backend/app/config_models.py:61-126`

All new fields optional; no `_check_required` changes (every field safely defaults to
"no native handling configured, fall back to footer/hooks"):

| Field | Type | Default | Applies to |
|---|---|---|---|
| `hooks_dir` | `str` | `""` | both — empty disables hook dispatch for this source |
| `in_progress_label` | `str` | `"kestrel-in-progress"` | github |
| `failed_label` | `str` | `"kestrel-failed"` | github |
| `escalated_label` | `str` | `"kestrel-escalated"` | github |
| `rejected_label` | `str` | `"kestrel-rejected"` | github |
| `transition_start` | `str` | `""` | jira — Jira workflow-transition id; `""` = no-op |
| `transition_done` | `str` | `""` | jira |
| `transition_failed` | `str` | `""` | jira |
| `transition_escalated` | `str` | `""` | jira |
| `transition_rejected` | `str` | `""` | jira |
| `time_spent_field` | `str` | `""` | jira — Jira field id for active time (e.g. `"timespent"` or a custom field); `""` = no native write, footer only |

No field for a native `wait_seconds` write exists (clarified: footer-only for wait
time across all platforms).

## `HookRunner` invocation payload (transient, not a persisted entity)

See `contracts/hook-wire-format.md` for the full stdin/stdout JSON schema. Built
directly from `WorkflowRun` + `LifecycleEvent` fields already listed above — no new
data collection is required.

## Relationships

- One `WorkflowRun` has at most one `TaskSourceConfig` (resolved via `run.source` →
  the `sources`/`code_hosts` dict built in `get_workflow_service()`,
  `workflows.py:2276-2339` — unchanged by this feature).
- One `LifecycleEvent` is built per lifecycle-worthy `_save()` call, from exactly the
  `WorkflowRun` that triggered it.
- `HookRunner` invokes zero or more hook executables per `LifecycleEvent`, all drawn
  from the one `hooks_dir` configured on that run's `TaskSourceConfig`.

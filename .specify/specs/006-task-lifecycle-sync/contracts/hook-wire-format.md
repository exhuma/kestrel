# Contract: operator hook wire format (stdin/stdout JSON)

This is the **operator-facing** contract — the actual "API" an operator's own script
authors against, per `hooks_dir` configured on a `TaskSourceConfig` entry. Implemented
by `HookRunner` (new `backend/app/services/hooks.py`), invoked by
`LifecycleTransitioner` (new `backend/app/services/lifecycle.py`) for every lifecycle
event on a source that has `hooks_dir` set.

## Discovery and invocation

- Every regular file directly inside the configured `hooks_dir` that is executable
  (`os.access(path, os.X_OK)`) is a hook. Non-executable files are silently skipped
  (allows a `README` or sample script alongside real hooks without extra config).
- Hooks run in filename-sorted order.
- Every hook is invoked for **every** lifecycle event on that source (clarified:
  single self-filtering location, not one script per named event) — a hook that only
  cares about, say, `failed` events inspects `kind` in the stdin payload and no-ops
  otherwise.
- Invocation: `asyncio.create_subprocess_exec(path, stdin=PIPE, stdout=PIPE,
  stderr=PIPE)` — **no `env=` override**, so the subprocess inherits kestrel's own
  process environment (FR-011). This is the mechanism by which a hook gains access to
  `KESTREL_GITHUB_TOKEN` / `KESTREL_JIRA_API_TOKEN` / any code-host token / anything
  else kestrel's own process has in its environment.
- Timeout: 30 seconds per hook invocation (clarified, FR-010). A hook still running
  after 30s is killed and that invocation is treated as failed.
- Failure isolation: a non-zero exit, a timeout, or unparseable stdout is logged
  (path + truncated stderr excerpt, never the full text — FR-013) and does not stop
  the remaining hooks for this event, nor kestrel's own built-in status/footer
  handling for the same event, nor the run itself.

## stdin: the event payload (JSON, one object, written then stdin closed)

```json
{
  "event": "done",
  "run_id": "b3f1...",
  "task_ref": "RFC-123",
  "source": "jira-issue",
  "active_seconds": 8040.5,
  "wait_seconds": 612.0,
  "pr_url": "https://github.com/acme/widgets/pull/42",
  "deep_link": "https://kestrel.internal/?run=b3f1...",
  "error": null
}
```

| Field | Type | Notes |
|---|---|---|
| `event` | string | One of `"start"`, `"done"`, `"failed"`, `"escalated"`, `"rejected"` — same value as `LifecycleEvent.kind` (see `contracts/task-source-protocol.md`). Applies identically for the three failure kinds — a hook is a first-class failure-handling mechanism (e.g. cleanup, paging), not a "done-only" hook. |
| `run_id` | string | Kestrel's own durable run id. |
| `task_ref` | string | Source-native ticket ref (`"owner/name#123"` for GitHub, `"RFC-123"` for Jira). |
| `source` | string | `run.source` — `"github-issue"` or `"jira-issue"`. |
| `active_seconds` | number \| null | `LifecycleEvent.active_seconds`. |
| `wait_seconds` | number \| null | `LifecycleEvent.wait_seconds`. |
| `pr_url` | string \| null | Set once a change request has been opened; `null` before then. |
| `deep_link` | string | Kestrel UI deep-link, or `""` if no public base URL is configured. |
| `error` | string \| null | A short, non-sensitive outcome note for `failed`/`escalated`/`rejected` events; `null` for `start`/`done`. |

## stdout: the optional response (JSON, or empty)

A hook may print nothing (exit 0, silent success) or a single JSON object:

```json
{"comment_posted": true}
```

| Field | Type | Effect |
|---|---|---|
| `comment_posted` | boolean | `true` tells kestrel this hook already posted its own comment for this event on the ticket, so kestrel skips **only** its own duplicate comment-footer post for this event. It does **not** suppress kestrel's own native status/time-field transition attempt (FR-009 — additive, always both). Absent or `false` ⇒ no effect. |

Empty stdout, non-JSON stdout, or a JSON value that isn't an object with a recognized
key is treated as `{}` (no effect) — never raises, never breaks the pipeline. If
multiple hooks run for the same event and any one of them returns
`comment_posted: true`, the footer is suppressed (any one hook claiming it posted a
comment is sufficient).

## Non-goals (explicitly out of scope for this wire format)

- No mechanism for a hook to override or veto kestrel's own native status transition —
  hooks are strictly additive (spec FR-009, clarified "additive, always-both"
  decision from the design phase).
- No mechanism for a hook to modify the `active_seconds`/`wait_seconds` values kestrel
  computed — those are read-only from the hook's perspective.
- No versioning field in the payload for this initial release — if the payload shape
  needs to change later, that is a follow-up decision, not pre-built here (YAGNI).

## Test contract (subprocess mocked, never a real executable spawned)

- A hook receiving a `start` event, `done` event, and each of the three failure kinds
  — asserts the JSON payload shape and field values match the table above exactly.
- A hook that exits non-zero, one that hangs past 30s, and one that prints invalid
  JSON to stdout — each asserts `HookRunner.run()` never raises, always returns a
  dict, and that a second, well-behaved hook configured alongside it still runs.
- A hook that prints `{"comment_posted": true}` — asserts the caller
  (`LifecycleTransitioner`) skips its own footer post for that event but still
  performs the native `transition()` attempt.
- Env-inheritance regression test: assert the mocked `create_subprocess_exec` call
  receives no explicit `env=` keyword (i.e., default inheritance) — guards the
  intentional decision in FR-011 against being silently "fixed" by a future change.

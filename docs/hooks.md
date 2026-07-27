# Operator hooks (feature 006)

Kestrel pushes a run's lifecycle status ("in progress", "done", or a
failure terminal) and its active/wait time back to a task's ticket —
natively where the platform supports it (a GitHub label, a configured
Jira transition), with a comment-footer fallback everywhere else. Some
platforms — Jira above all — are configured with workflow transitions and
custom fields kestrel cannot anticipate. **Operator hooks** are the escape
hatch: a folder of executables, git-hook style, invoked at every lifecycle
event so you can bolt on whatever your own instance needs.

## ⚠️ Security: read this before setting `hooks_dir`

**A hook subprocess inherits kestrel's entire process environment,
including every configured credential** (`KESTREL_GITHUB_TOKEN`,
`KESTREL_JIRA_API_TOKEN`, `KESTREL_CODE_HOST_TOKEN`, anything else kestrel
has). This is intentional — a hook can call the same ticket-tracker API
kestrel itself uses, with kestrel's own token, to perform a custom action
kestrel doesn't natively support.

This means **`hooks_dir` and everything in it must be treated with
exactly the same care as `config.toml` or the secrets it references.**
Only point `hooks_dir` at a directory you fully control and trust — never
a shared, externally-writable, or otherwise less-trusted location. There
is no sandboxing: a hook runs with the full authority kestrel's own
process has. At startup kestrel logs every executable it finds in a
configured `hooks_dir` (and flags any that are group/world-writable at
`WARNING`) so you have a chance to notice something unexpected — but this
is a nudge, not an access control. The operator's own judgment about what
belongs in that directory is the only real safeguard, exactly as with
git's own hook mechanism.

## Configure

Set `hooks_dir` on a `[[task_sources]]` entry in `config.toml` (see
[Configuration → Task sources](configuration.md#task-sources)):

```toml
[[task_sources]]
type = "jira"
# ... the rest of the entry ...
hooks_dir = "/path/to/hooks/jira"   # only scripts you trust, see above
```

Unset (the default) disables hook dispatch for that source entirely — no
filesystem access is attempted.

`hooks_dir` must be a path **inside the kestrel process's own filesystem
view** — when running the published container, that means a path inside
the container, not a host path. Mount your hooks directory as a volume and
point `hooks_dir` at the container-side path (see the commented example in
`docker-compose.yml`):

```yaml
volumes:
  - ./hooks/jira:/hooks/jira:ro
```

```toml
hooks_dir = "/hooks/jira"   # the container-side path above
```

Running from source, `hooks_dir` is just a normal path on the host.

## What runs, and when

Every executable file directly inside `hooks_dir` is a hook (non-executable
files, e.g. a `README`, are skipped). Hooks run in filename-sorted order.
**Every hook is invoked for every lifecycle event** — there's no
per-event-named-script convention — so a script that only cares about,
say, a failed run inspects the event and no-ops otherwise:

| Event | Fires when |
|---|---|
| `start` | The run begins working the ticket. |
| `done` | The run delivers a change request successfully. |
| `failed` | The run fails. |
| `escalated` | The run is escalated for human attention. |
| `rejected` | The PRD is rejected with no further feedback. |

Hooks are **strictly additive**: kestrel always attempts its own native
status/time-tracking transition and comment-footer fallback regardless of
what a hook does. A hook can only ever add to that, never replace or
suppress it — with one narrow exception (see `comment_posted` below).

A hook that hangs is killed after **30 seconds** and treated as failed for
that invocation. A hook that exits non-zero, times out, or produces
unparseable output is logged and skipped — it never blocks another
configured hook, kestrel's own lifecycle handling, or the run itself.

## Wire format

The hook receives one JSON object on stdin, then stdin is closed:

```json
{
  "event": "done",
  "run_id": "b3f1c2a4-...",
  "task_ref": "RFC-123",
  "source": "jira-issue",
  "active_seconds": 8040.5,
  "wait_seconds": 612.0,
  "pr_url": "https://github.com/acme/widgets/pull/42",
  "deep_link": "https://kestrel.internal/?run=b3f1c2a4-...",
  "error": null
}
```

| Field | Type | Notes |
|---|---|---|
| `event` | string | One of `start`, `done`, `failed`, `escalated`, `rejected`. |
| `run_id` | string | Kestrel's own durable run id. |
| `task_ref` | string | The ticket's native ref (`"owner/name#123"` for GitHub, `"RFC-123"` for Jira). |
| `source` | string | `"github-issue"` or `"jira-issue"`. |
| `active_seconds` | number \| null | Cumulative active-work time; `null` for `start` (nothing to report yet). |
| `wait_seconds` | number \| null | Cumulative time parked waiting on you; `null` for `start`. |
| `pr_url` | string \| null | Set once a change request has been opened. |
| `deep_link` | string | Kestrel's own UI link for this run, or `""` if no public base URL is configured. |
| `error` | string \| null | A short outcome note for a failure event; `null` for `start`/`done`. |

A hook may print nothing (silent success) or a single JSON object on
stdout:

```json
{"comment_posted": true}
```

`comment_posted: true` tells kestrel this hook already posted its own
comment for this event, so kestrel skips **only** its own duplicate
comment-footer post — the native status/time-tracking transition still
happens regardless. Empty, invalid, or unrecognized stdout has no effect
and never breaks the pipeline.

## Example

```sh
#!/bin/sh
# hooks/jira/notify-oncall.sh — page on failure, ignore everything else.
event=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["event"])')
if [ "$event" = "failed" ] || [ "$event" = "escalated" ]; then
  curl -sf -X POST "$PAGER_WEBHOOK_URL" -d "kestrel run failed"
fi
```

Make it executable (`chmod +x`) and point `hooks_dir` at its containing
folder.

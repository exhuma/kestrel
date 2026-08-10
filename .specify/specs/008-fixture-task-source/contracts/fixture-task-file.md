# Contract: fixture task file format

Defined by `FixtureTaskSource`/`FixturePollService`
(`backend/app/services/fixture.py`, `fixture_poll.py`). This is the surface
an admin directly authors and edits by hand (spec Assumptions: no dedicated
UI for creating/editing fixture tasks in this feature) — so it is a real
contract even though nothing calls it over HTTP.

## Location

One JSON file per task, directly under the fixture source's configured
`fixtures_dir` (`TaskSourceConfig.fixtures_dir`):

```text
<fixtures_dir>/
├── retry-checkout-bug.json
├── retry-checkout-bug.log            # created on first post_comment()
├── retry-checkout-bug.attachments/   # created on first attach(), if any
└── another-task.json
```

The filename stem (`retry-checkout-bug`) is the task's identifier, used
verbatim to build `task_ref = "fixture:<stem>"`.

## `<slug>.json` schema

```json
{
  "title": "Fix the checkout race condition",
  "body": "When two tabs submit checkout simultaneously, ...",
  "code_repo": "myorg/sandbox-repo",
  "base_branch": "main"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `title` | `string` | yes | Maps to `Task.title` — the run's issue/ticket title equivalent. |
| `body` | `string` | yes | Maps to `Task.body`. Overwritten in place by `publish_refined()` once the refine step's PRD is approved — editing it back by hand before a rerun is how an admin "retries with a tweak." |
| `code_repo` | `string` | yes | `owner/name`. Resolved the same way a Jira RFC's resolved repo is used today: passed as `code_repo` to `ingestion.maybe_start_run`. Must be reachable via the fixture source's configured `code_host`/`code_host_base_url`/`code_host_token_env` (reused from `TaskSourceConfig`, not fixture-specific — see `research.md` §5). |
| `base_branch` | `string \| null` | no | Passed through to `maybe_start_run`; `null`/absent defers to the code host's default branch, same as every other source. |

## Behavioral notes

- **Read fresh every time**: `get_task()` re-reads the file on every call —
  no in-process cache. Editing `title`/`body` between runs is picked up
  immediately on the next run without a service restart (spec FR-005).
- **Write-back stays local**: `post_comment`/`attach`/`publish_refined` only
  ever write to `<slug>.log` / `<slug>.attachments/` / the JSON file itself
  — never to a network endpoint (spec FR-003).
- **Deletion mid-run**: if the file is removed while a run references it,
  `get_task()` raises; the run surfaces this as its error state, identical
  to how an unreachable GitHub/Jira ticket already fails a run today (spec
  Edge Cases).
- **Collision**: two files with the same stem cannot exist (filesystem
  invariant); an admin renaming a file changes its `task_ref` and therefore
  its identity — treated as a new task, matching spec Edge Cases (`"MUST
  NOT silently merge or overwrite one task's history"`).

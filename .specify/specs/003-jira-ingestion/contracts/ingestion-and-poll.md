# Contract: source-neutral ingestion + Jira poll

## `IngestionService.maybe_start_run(...)` — generalized (`services/ingestion.py`)

The single choke point every trigger (GitHub webhook, GitHub reconcile, Jira poll) calls
(FR-031, FR-034). Generalized from `(repo, issue_number, *, source)` to a source-neutral
signature keyed on `task_ref`.

```
async maybe_start_run(
    *, source: str, task_ref: str, code_repo: str,
    base_branch: str | None = None, title: str = "",
) -> str | None
```

- Skips and returns `None` when: the ticket already has a run (`one-run-per task_ref`), or
  `task_ref` is dismissed (`DismissalStore.is_dismissed`), or (GitHub) the repo is not watched.
- Otherwise calls `WorkflowRegistry.create(...)` / `WorkflowService.create(...)` with `source`,
  `task_ref`, `code_repo`, and starts the run; returns the run id.
- Records the observation outcome in structured logs: `started` | `skipped-duplicate` |
  `skipped-filtered` | `unresolved-repo` | `dismissed` | `failed` (FR-035).
- GitHub callers pass `task_ref=f"{repo}#{issue_number}"`, `code_repo=repo`; the reconcile/webhook
  wrappers (`services/reconcile.py`, `routers/github_webhook.py`) are updated to the new
  signature with no behaviour change.

## `WorkflowService.create(...)` — generalized (`services/workflows.py:417`)

```
async create(
    *, source: str, task_ref: str, code_repo: str,
    issue_number: int | None = None, base_branch: str | None = None,
) -> str
```

- Builds a `WorkflowRun` with `source`, `task_ref`, `repo=code_repo`, steps
  `["refine", "design", "code", "verify"]`, branch derived per source (GitHub:
  `kestrel/issue-{n}`; Jira: `kestrel/{slugified task_ref}`), and spawns `_drive`.
- `_drive` resolves the run's `TaskSource`/`CodeHost` from `source`, fetches the task
  (`get_task`), resolves `base_branch` via `CodeHost.get_default_branch` when unset, provisions
  the worktree from `CodeHost.clone_remote(code_repo)`, and refines from the task body.

## `JiraPollService.run_forever()` (`services/jira_poll.py`)

Mirrors `ReconcileService.run_forever()` (`services/reconcile.py:66`).

- Runs a cycle immediately, then sleeps `jira_poll_interval_seconds`.
- Each cycle: `JiraClient.search(jql)` where `jql = 'project = "{jira_project}"'` AND
  (`jira_jql_filter` when set); for each RFC, resolve the repo via `get_field(key,
  jira_repo_field)` and probe it with `CodeHost.get_default_branch` (R-09); then
  `maybe_start_run(source="jira-issue", task_ref=key, code_repo=repo, base_branch=…, title=…)`.
- On an unresolved/unreachable repo: no run; log `unresolved-repo`; post a thin RFC comment that
  the target repo could not be determined (FR-007).
- **Dismissal clear (re-trigger gesture, FR-033)**: each cycle clears the dismissal of any
  previously-dismissed Jira RFC that no longer appears in the qualifying result set (the RFC left
  the JQL), so re-qualifying it starts a fresh run — mirroring the GitHub reconcile clear
  (`services/reconcile.py`). A dismissed RFC that still matches the JQL stays suppressed.
- On a Jira outage/query error: log and continue next cycle; start no partial runs (FR-003).
- Started in the lifespan (`main.py:63-77`) only when `jira_base_url` and `jira_project` are set;
  cancelled on shutdown — same pattern as the GitHub reconciler.

## Test contract

- Two overlapping cycles / a simulated restart → exactly one run per RFC (FR-031, FR-032).
- A qualifying RFC with a resolvable repo → one run with `source="jira-issue"`,
  `repo=<resolved>`, `task_ref=<key>`.
- Empty/unreachable repo field → no run + `unresolved-repo` + one RFC comment.
- A dismissed RFC still matching the JQL → no run.
- A dismissed RFC that no longer matches the JQL → its dismissal is cleared; re-qualifying starts
  a fresh run (FR-033).
- GitHub webhook/reconcile still produce identical runs through the generalized entry point.

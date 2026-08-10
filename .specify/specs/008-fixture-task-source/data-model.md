# Phase 1 Data Model: Fixture Task Source & Rerun

## `TaskSource` protocol (extended) — `backend/app/ports.py`

| Member | Type | Notes |
|---|---|---|
| `visibility()` | `() -> Literal["public", "private"]` | **NEW.** Static per-source capability, same shape as the existing `supports_time_spent()` — never varies across invocations. `GitHubTaskSource`/`JiraTaskSource` return `"public"`; `FixtureTaskSource` returns `"private"`. The sole gate for the rerun action (see below); no other behavior reads it in v1. |

All existing members (`get_task`, `post_comment`, `attach`,
`publish_refined`, `deep_link_ref`, `transition`, `supports_time_spent`) are
unchanged; `FixtureTaskSource` implements every one of them (see below).

## `FixtureTaskSource` (new) — `backend/app/services/fixture.py`

Implements `TaskSource`, backed entirely by files under a configured
`fixtures_dir`. No network calls.

| Method | Behavior |
|---|---|
| `get_task(ref)` | `ref` is `"fixture:<slug>"`. Reads `fixtures_dir/<slug>.json` fresh on every call. Returns `Task(ref=ref, title=data["title"], body=data["body"])`. Raises if the file is missing (surfaces as the run's error state, same as an unreachable GitHub/Jira ticket would). |
| `post_comment(ref, body)` | Appends a timestamped entry to `fixtures_dir/<slug>.log` (created on first write). Returns the log file's path as its "URL". |
| `attach(ref, name, data, mimetype)` | Writes `data` to `fixtures_dir/<slug>.attachments/<name>`; no-op-safe if the directory can't be created (matches the protocol's "may no-op" allowance, same as GitHub's issue-attachment no-op). |
| `publish_refined(ref, content)` | Overwrites the task file's `body` field with `content` (the local analogue of GitHub's body-PATCH / Jira's field write). |
| `deep_link_ref(ref)` | Returns the absolute path to the fixture file (or `""` if it no longer exists). |
| `transition(ref, event)` | No native status mechanism — always returns `False` (falls back to the comment-footer, same as any source with no configured lifecycle mapping). |
| `supports_time_spent()` | `False` — no native time field. |
| `visibility()` | `"private"` — see above. |

## `FixturePollService` (new) — `backend/app/services/fixture_poll.py`

Implements `PollSource` (`backend/app/services/poll_source.py`).

| Member | Behavior |
|---|---|
| `name` | `"fixture"` — matches `ReconcileService`/`JiraPollService`'s existing `name` usage in logs/CLI output. |
| `list_work_items()` | Lists `*.json` files in `fixtures_dir`; returns one `WorkItem(source="fixture-issue", ref="fixture:<slug>", title=..., code_repo=..., base_branch=...)` per file — the existing dry-run listing shape (`ports.py::WorkItem`), used by `python -m app poll`. |
| `run_forever()` | For each file, calls `ingestion.maybe_start_run(source="fixture-issue", task_ref="fixture:<slug>", code_repo=..., base_branch=...)` — deduped for free by the existing `has_run(task_ref)` check inside `maybe_start_run`, same as GitHub/Jira. Sleeps `settings.poll_interval_seconds` between passes, matching the existing poll services. |

## `TaskSourceConfig` (extended) — `backend/app/config_models.py`

| Field | Type | Default | Notes |
|---|---|---|---|
| `type` | `Literal["github", "jira", "fixture"]` | — | **Extended** (was `["github", "jira"]`). |
| `fixtures_dir` | `str` | `""` | **NEW.** Directory of fixture task files. Required when `type == "fixture"` (enforced in `_check_required`, same validation shape as GitHub's `watched_repos`/Jira's `base_url`+`jql`+`key`). |

No other new fields: a fixture entry reuses the **existing** `code_host` /
`code_host_base_url` / `code_host_token_env` fields (today only used by
Jira) for its code-hosting target, per the research.md §5 decision — no
duplication of that config surface.

`_check_required` gains one branch:

```text
if self.type == "fixture" and not self.fixtures_dir:
    raise ValueError("fixture task source requires fixtures_dir")
```

## `WorkflowRun` — `backend/app/models_workflow.py` / `WorkflowRunRow`

**Unchanged.** `source` already accepts any string (no enum constraint in
either the dataclass or the SQLAlchemy column — confirmed in
`persistence/tables.py`); this feature only adds a new *value*,
`"fixture-issue"`, to the set it's ever assigned. No migration.

## `WorkflowSummary` / `WorkflowDetail` (extended) — `backend/app/schemas.py`

| Field | Type | Notes |
|---|---|---|
| `rerunnable` | `bool` | **NEW**, on both schemas. Computed in `routers/workflows.py`'s `_detail()`/`_summaries()` as `service._task_source(run).visibility() == "private"` — same "compute at read time from a service call" pattern as the existing `allow_incomplete_answers` (`_detail()` line 99, from `get_settings()`). Never persisted. |

Mirrored on the frontend, per Constitution Principle I's type-contract
rule: `frontend/src/types/workflows.ts` `WorkflowSummary`/`WorkflowDetail`
gain the same `rerunnable: boolean` field.

## `RerunNotAllowedError` (new) — `backend/app/services/exceptions.py`

```python
class RerunNotAllowedError(Exception):
    """Raised when rerun is attempted on a run whose task source is not private."""
```

Mapped in `main.py` to HTTP 403 (see `research.md` §4 for the 403-vs-409
rationale).

## New service method: `WorkflowService.rerun()` — `backend/app/services/workflows/service.py`

```text
async def rerun(self, workflow_id: str) -> str:
    run = self.get(workflow_id)
    if self._task_source(run).visibility() != "private":
        raise RerunNotAllowedError(workflow_id)
    task_ref, code_repo = run.task_ref, run.repo
    issue_number, base_branch, source = run.issue_number, run.base_branch, run.source
    # reuse cleanup()'s body: _abandon_common + branch delete (local + remote)
    # + dismissal clear — then, unlike cleanup(), immediately re-ingest:
    return await self._ingestion.maybe_start_run(
        source=source, task_ref=task_ref, code_repo=code_repo,
        issue_number=issue_number, base_branch=base_branch,
    )
```

Returns the new run's id (the router's `POST /rerun` response echoes it,
matching `POST /api/workflows`'s existing `{"workflow_id": ...}` shape).
`WorkflowService` gains a constructor dependency on `IngestionService` (or
an injected callable) to call `maybe_start_run` — the exact wiring
(direct dependency vs. a passed-in callback) is an implementation-phase
detail; either keeps `rerun()`'s single external effect (starting a fresh
run) explicit and testable without a real poll cycle.

## Relationships

```text
TaskSourceConfig (type="fixture", fixtures_dir, code_host*)
        │ builds (bootstrap.py)
        ▼
FixtureTaskSource ──implements──► TaskSource (+ visibility())
        │                                  ▲
        │ used by                          │ read by
        ▼                                  │
FixturePollService ──calls──► ingestion.maybe_start_run ──creates──► WorkflowRun(source="fixture-issue")
                                                                              │
                                                                              │ read by
                                                                              ▼
                                                      WorkflowService.rerun() ──guards on── visibility()
                                                                              │
                                                                              ▼
                                                          WorkflowSummary/Detail.rerunnable (API/UI)
```

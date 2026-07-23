# Phase 1 Data Model: Task-source configuration abstraction & poll tooling

No persistent (database) entities are added or changed — this feature is
configuration + an in-memory dry-run view. "Entities" here are the config models
and the transient value objects.

## `TaskSourceConfig` (pydantic `BaseModel`, config-time)

One entry of the file-only `task_sources` list. A single model discriminated by
`type`; per-type fields are optional at the type level and enforced by a model
validator.

| Field | Type | Applies to | Notes |
|-------|------|-----------|-------|
| `type` | `Literal["github", "jira"]` | all | Discriminator. Unknown value → config load error (Edge Case). |
| `token_env` | `str` | all | Name of the env var holding the token. Defaults per type (github → `KESTREL_GITHUB_TOKEN`, jira → `KESTREL_JIRA_API_TOKEN`). |
| `watched_repos` | `list[str]` | github | `owner/name` allow-list. Required (non-empty) for github. |
| `trigger_label` | `str` | github | Default `"kestrel"`. |
| `base_url` | `str` | jira | Jira instance base URL. Required for jira. |
| `auth` | `Literal["basic", "bearer"]` | jira | Default `"basic"`. |
| `email` | `str` | jira | Basic-auth identity (Cloud email). |
| `jql` | `str` | jira | One whole JQL query (folds project + filter). Required for jira. |
| `key` | `str` | jira | Source-native ref **prefix** (e.g. `"RFC"`), used only to scope this source's dismissal-clear/re-trigger gesture (dismissed refs `"{key}-…"`). Required for jira (issue keys are `KEY-N`). |
| `repo_field` | `str` | jira | Optional custom field id holding `owner/name[@base]`. |
| `repo_link_text` | `str` | jira | Web-link title to match. Default `"Repository"`. |
| `code_host` | `Literal["github", "gitlab", "gitea"]` | jira | Default `"github"`. |
| `code_host_base_url` | `str` | jira | Self-hosted host URL (gitlab/gitea). |
| `code_host_token_env` | `str` | jira | Env var name for the code-host token; falls back to the github token when `code_host="github"`. |

**Methods**:
- `token() -> str | None` — `os.environ.get(self.token_env)` (mirrors
  `BackendConfig.secret()`).
- `code_host_token() -> str | None` — resolves the code-host token env for a
  jira entry.

**Validation** (`@model_validator`):
- `github` requires a non-empty `watched_repos`.
- `jira` requires `base_url` and `jql`.
- Missing required fields → a loud config error at startup (never silent).

## `Settings` changes (`app/config.py`)

**Added**:
- `task_sources: list[TaskSourceConfig] = []` — **file-only** (added to
  `_FILE_ONLY_FIELDS`; built in `_apply_config_file` from `data["task_sources"]`).
- `poll_interval_seconds: int = 300` — the single re-check cadence.

**Removed** (breaking, D8): `watched_repos`, `trigger_label`, `jira_project`,
`jira_jql_filter`, `jira_base_url`, `jira_auth`, `jira_email`, `jira_repo_field`,
`code_host`, `code_host_base_url`, `code_host_token`, `reconcile_interval_seconds`,
`jira_poll_interval_seconds`. (`extra="ignore"` keeps any stale env key inert.)

**Kept**: `github_token`, `github_api_base`, `git_base`, `jira_api_token`,
`webhook_secret`, `public_base_url`, `verify_checks`, `max_verify_iterations`,
and the change-set-A `host`/`port`/`reload`. `verify_checks` /
`max_verify_iterations` remain top-level applicative keys (run-execution knobs,
not source selection).

**Helpers** (keep rewired consumers within limits):
- `github_sources() -> list[TaskSourceConfig]` / `jira_sources()` — filter by type.
- `github_source_for(repo: str) -> TaskSourceConfig | None` — the github entry
  whose `watched_repos` contains `repo` (webhook + reconcile use this).

**Retargeted validators**: the two "half-configured" warnings now iterate
`task_sources` (e.g. a jira entry whose `token()` is unset, or a
gitlab/gitea entry missing `code_host_base_url`/token) and warn without failing.

## `WorkItem` (dataclass, poll-time, `app/services/poll_source.py`)

Transient view produced by the dry-run listing; persists nothing, starts no run.

| Field | Type | Notes |
|-------|------|-------|
| `source` | `str` | Run-source label (`github-issue` \| `jira-issue`). |
| `ref` | `str` | Source-native id (`owner/name#123` \| `RFC-123`). |
| `title` | `str` | Item title. |
| `code_repo` | `str \| None` | Resolved `owner/name`, or `None` when unresolved. |
| `base_branch` | `str \| None` | Resolved base branch (jira), else `None`. |

## `PollSource` (Protocol, `app/services/poll_source.py`)

Poll-time listing role — distinct from `ports.py`'s run-time
`TaskSource`/`CodeHost`.

- `name: str` — display label for the CLI grouping.
- `async list_work_items() -> list[WorkItem]` — run this source's selection
  query and resolve each item's repo; **no ingestion**.

`configured_poll_sources(settings) -> list[PollSource]` — one entry per
configured `task_sources` element (reconcile-backed for github, jira-poll-backed
for jira). Consumed by both the lifespan (a `run_forever` task per entry) and the
CLI.

## Service shape changes (behaviour-preserving)

- **`ReconcileService`** — parameterized by one github `TaskSourceConfig`
  (repos + label + client). `_list_labelled(repo)` extracted; `run_cycle` and
  `list_work_items` both call it. Dismissal-clear scoped to this source's repos.
- **`JiraPollService`** — parameterized by one jira `TaskSourceConfig` (client +
  jql + `key` + repo-resolution + its code host). `_search_tasks()` extracted;
  `_resolve_repo` split per D6; `list_work_items` reuses them without
  `maybe_start_run`. Dismissal-clear scoped to this source via the entry's `key`
  prefix (`f"{entry.key}-"`), replacing the former `jira_project` prefix.
- **`IngestionService.is_watched(repo)`** — true when any github source's
  `watched_repos` contains `repo`.
- **`get_workflow_service()` registry** — `sources` / `code_hosts` dicts built by
  scanning `task_sources` (github entries → GitHub adapters; jira entries → Jira
  `TaskSource` + the entry's configured code host).
- **`github_webhook` router** — `watched` / trigger-label decided via
  `settings.github_source_for(repo)` and that entry's `trigger_label`.

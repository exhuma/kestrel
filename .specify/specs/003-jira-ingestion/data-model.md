# Data Model: Jira Ingestion & Autonomous Design/Code/Verify Loop

The schema is owned exclusively by Alembic (Constitution II). All changes ship in one new
revision **`0007_jira_ingestion`** with `down_revision = "0006"` (the ingestion revision that
added `webhook_delivery`, `issue_dismissal`, and `workflow_run.source`). Timestamps are naive
UTC; stores keep their own `Session` lifecycle (constitution deviations, preserved).

## Modified table: `workflow_run` (+ `task_ref`, `issue_number` nullable)

Generalize the run's identity so a Jira RFC (which has no `(repo, issue_number)`) fits the same
row (R-04). `repo` keeps its meaning as the **code repository** (unchanged for GitHub; the
resolved repo for Jira), so worktree/PR paths are untouched.

| Column | Type | Notes |
|--------|------|-------|
| `task_ref` | `String`, server_default `""` | NEW. Source-native ticket id: GitHub `owner/name#123`, Jira issue key `RFC-123`. Universal key for dedup, dismissal, notification rendering (FR-024, FR-031, FR-033). |
| `issue_number` | `Integer`, **nullable** | CHANGED from NOT NULL. GitHub-only; `NULL` for Jira runs. |
| `repo` | `String` | Unchanged meaning: the code repository. For Jira, the resolved `owner/name`. |
| `source` | `String`, default/server_default `"manual"` | Unchanged column; NEW permitted value `"jira-issue"` (with `"manual"`, `"github-issue"`). Internal-only (FR-026). |

**Rules**
- Migration backfills `task_ref` for existing rows: `task_ref = repo || '#' || issue_number`
  (all pre-existing runs are GitHub/manual with an `issue_number`). Executed as a data step in
  `0007` before dropping the NOT NULL on `issue_number` (SQLite `batch_alter_table`).
- New runs always set `task_ref`: GitHub ingestion/manual → `f"{repo}#{issue_number}"`; Jira →
  the issue key.
- `source` MUST NOT influence which phases/gates a run traverses (FR-026); it selects the
  bound `TaskSource`/`CodeHost` and the notification surface only.
- No `task_ref` uniqueness constraint at the DB level; one-run-per-ticket is enforced by the
  ingestion guard (R-10), matching how 002 enforces one-run-per-issue in the service layer.

## Modified table: `issue_dismissal` → source-neutral dismissal

Generalize the tombstone from `(repo, issue_number)` to the universal `task_ref` so a rejected
or abandoned Jira RFC is suppressed the same way (FR-033).

| Column | Type | Notes |
|--------|------|-------|
| `task_ref` | `String` PK | NEW primary key. Replaces the `(repo, issue_number)` composite PK. |
| `created_at` | `DateTime` | naive UTC. |

**Rules**
- `0007` rebuilds the table via `batch_alter_table`: add `task_ref`, backfill
  `repo || '#' || issue_number`, drop `repo`/`issue_number`, set `task_ref` as PK.
- `DismissalStore` (`persistence/dismissal_store.py`) is generalized: `add(task_ref)`,
  `is_dismissed(task_ref) -> bool`, `clear(task_ref)`. GitHub's dismissal call sites pass
  `f"{repo}#{issue_number}"`.
- A dismissal is created on PRD rejection or run abandon (FR-033); cleared by the source's
  re-trigger gesture (GitHub: label removed/re-added — existing; Jira: the RFC leaving/re-
  entering the qualifying JQL — see "Validation rules").

## Unchanged tables

`webhook_delivery` (GitHub-only dedup), `session`, `event`, `workflow_step`, `notification`
are structurally unchanged. `notification.status` gains the new run-status **values**
(`escalated` and the transient ones are not notified); no column change. `notification`
continues to store `repo`/`issue_number`; rendering uses `task_ref` from the run (R-08), and
these columns may be `NULL`/`0` for Jira rows without a schema change (they are display-only).

## Domain model changes

### `WorkflowRun` (`models_workflow.py`)

| Field | Change |
|-------|--------|
| `task_ref: str = ""` | NEW — mirrors the column; the universal ticket id. |
| `issue_number: int \| None` | CHANGED to `Optional`; `None` for Jira. |
| `source: str = "manual"` | Unchanged; `"jira-issue"` is a new value. |
| `steps` | Built as `["refine", "design", "code", "verify"]` (was `refine`/`plan`/`implement`). |

`WorkflowStep`, `StepSession` unchanged in shape. The `verify` step's `deliverable` holds the
latest verdict summary plus a compact rendering of the evidence (which checks passed/failed);
its `active_sessions` chip is the `verifier`. The in-memory verify iteration count and the
gathered evidence live on the driver's `_Control`, not on the persisted model (R-06).

### Run status set (reshaped state machine — see `contracts/workflow-states.md`)

`pending`, `cloning`, `refining`, `awaiting_refine_input`, `awaiting_refine_approval`,
`designing`, `coding`, `verifying`, `opening_pr`, `done`, `failed`, `rejected`, **`escalated`**.
`_TRANSIENT` (fail-on-restart): `pending`, `cloning`, `refining`, `designing`, `coding`,
`verifying`, `opening_pr`. Gates (`awaiting_*`, re-parked on restart): `awaiting_refine_input`,
`awaiting_refine_approval`. Terminal: `done`, `failed`, `rejected`, `escalated`.

## Ports (in-memory contracts, not persisted) — `ports.py`

- `Task(ref: str, title: str, body: str)`.
- `TaskSource`: `get_task`, `post_comment`, `attach`, `publish_refined`, `list_open`,
  `deep_link_ref`. Implemented by `GitHubTaskSource`, `JiraTaskSource`.
- `CodeHost`: `get_default_branch`, `open_change_request`, `clone_remote`. Implemented by
  `GitHubCodeHost` (pull request) **and** `GitLabCodeHost` (self-hosted GitLab merge request);
  selected by `code_host` config. Gitea/Forgejo is the same port, added when needed (R-03).
- `Observation(name: str, kind: Literal["http","ui","check"], passed: bool, detail: str)` and
  `Evidence(observations: list[Observation])` — the verifier's grounding. The design **assumes**
  behavioural verification (run the app + exercise its boundary → `http`/`ui` observations,
  R-06); v1 ships a minimal `check` gatherer (`services/checks.py::CheckRunner` over
  `verify_checks`), with the HTTP/Playwright harness designed-for but deferred. Passed into the
  verify phase and the coder feedback; in-memory only (a compact summary lands in the verify
  step's `deliverable`).

See `contracts/task-source-port.md`, `contracts/code-host-port.md`, `contracts/verify-evidence.md`.

## Configuration entities (`config.py`, env `KESTREL_*`)

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| `jira_base_url` | `str` | `""` | Jira instance base URL; empty ⇒ Jira polling disabled. |
| `jira_auth` | `Literal["basic","bearer"]` | `"basic"` | `basic` = Cloud email+API-token; `bearer` = Server/DC PAT. |
| `jira_email` | `str` | `""` | Basic-auth username (Cloud). |
| `jira_api_token` | `str` (secret) | `""` | API token / PAT. Never logged/committed (FR-004). |
| `jira_project` | `str` | `""` | RFC project key; required to poll. |
| `jira_jql_filter` | `str` | `""` | Extra JQL AND-ed onto `project = "<key>"` (e.g. `status = "Ready"`). Agnostic knob (FR-005). |
| `jira_repo_field` | `str` | `""` | Field id/name holding the target `owner/name[@branch]` (FR-006). |
| `jira_poll_interval_seconds` | `int` | `300` | Poll cadence (FR-002). |
| `code_host` | `Literal["github","gitlab","gitea"]` | `"github"` | Code host for Jira-resolved repos; `gitlab` = self-hosted GitLab (FR-023a). |
| `code_host_base_url` | `str` | `""` | Self-hosted code-host instance URL (e.g. `https://gitlab.internal`). |
| `code_host_token` | `str` (secret) | `""` | Code-host token (PAT). Falls back to `github_token` when `code_host="github"`. Never logged. |
| `verify_checks` | `list[str]` | `[]` | Shell commands run in the worktree as verify evidence (e.g. `["uv run pytest","npm test"]`) (FR-015a). |
| `max_verify_iterations` | `int` | `3` | Max code↔verify rounds before escalation (FR-017). Source-neutral. |

Reused: `public_base_url` (deep-links), `git_base` + `github_token` (GitHub CodeHost + git
auth). `model_validator`s warn when `jira_base_url` is set without `jira_project`/`jira_api_token`,
and when `code_host` is a self-hosted type without `code_host_base_url`/`code_host_token`
(mirrors `config.py:215-228`).

## Relationships & lifecycle

```text
Jira poll cycle ─┐                         ┌─ TaskSource(jira)  ── comment/attach/deep-link
                 ├─► IngestionService ──► WorkflowRun(source, task_ref, repo)
GitHub webhook ──┤   .maybe_start_run       │  refine → PRD approval → design → code → verify
GitHub reconcile─┘   (task_ref guard)       └─ CodeHost(github)  ── worktree / pull request
                          │                          ▲
                     DismissalStore(task_ref)        │  verify: accept → deliver
                     one-run-per task_ref            └─ reject (< max_iter) → code ; exhausted → escalated
```

## Validation rules (from requirements)

- **One run per `task_ref`** — the ingestion guard starts at most one run per ticket across
  poll cycles and restarts (FR-031, FR-032).
- **Repo resolution** — a run starts only when `jira_repo_field` yields a repo resolvable and
  reachable on the **configured code host** (GitHub or a self-hosted GitLab/Gitea per
  `code_host`); otherwise no run + `unresolved-repo` outcome + a thin RFC comment (FR-007). A
  missing field on the schema is an operator-misconfig log (FR-008).
- **Dismissal** — PRD rejection / abandon writes `task_ref` to `issue_dismissal` (stop-and-
  dismiss, FR-012); ingestion skips a dismissed ticket while it still qualifies (FR-033). For
  Jira the re-trigger gesture is the RFC leaving and re-entering the qualifying JQL: the poll
  **clears** a Jira dismissal when its RFC no longer appears in the qualifying set (mirroring the
  GitHub reconcile clear). For GitHub the existing label remove/re-add gesture is unchanged.
- **Verify bound** — code↔verify never exceeds `max_verify_iterations`; on exhaustion the run
  is `escalated` and no change request is opened (FR-016, FR-017, FR-018).
- **Evidence grounding** — the design assumes behavioural verification (run the modified project,
  exercise its boundary via HTTP/Playwright → observations); v1 gathers `check` observations from
  `verify_checks`. Any failing observation never yields an `accept` verdict, and failing
  observations are fed back to the coder. No observations ⇒ judgment-only fallback, interface
  still carries `Evidence` (FR-015a, FR-015b, SC-006a).
- **Thin notifications** — comment bodies are fixed templates with only status + link; the PRD
  is an attachment (FR-011, FR-029). Credentials never appear in logs or comments (FR-004,
  FR-009).
- **Source is internal** — `source`/`task_ref` are never added to the API schema or
  `frontend/src/types/`, and never change which phases/gates a run runs (FR-026).

# Quickstart: Fixture Task Source & Rerun

Runnable validation scenarios that prove the feature end-to-end. See
[data-model.md](./data-model.md) and [contracts/](./contracts/) for shapes;
this guide is the run/validation checklist, not implementation.

## Prerequisites

- No Alembic migration to apply (see `research.md` §3 — this feature adds no
  schema).
- Configure a fixture task source in `config.toml` (file-only, like every
  `[[task_sources]]` entry):

  ```toml
  [[task_sources]]
  type = "fixture"
  fixtures_dir = "/home/you/kestrel-fixtures"
  # Reuses the same code-host fields Jira sources use:
  code_host = "github"                 # github | gitlab | gitea
  code_host_token_env = "KESTREL_GITHUB_TOKEN"
  ```

- Create the fixtures directory and one task file (see
  `contracts/fixture-task-file.md` for the full schema):

  ```bash
  mkdir -p /home/you/kestrel-fixtures
  cat > /home/you/kestrel-fixtures/hello-fixture.json <<'JSON'
  {
    "title": "Add a hello-world endpoint",
    "body": "Add GET /hello returning {\"msg\": \"hello\"}.",
    "code_repo": "you/sandbox-repo",
    "base_branch": "main"
  }
  JSON
  ```

- `sandbox-repo` MUST be a real, reachable repository the configured
  `code_host` token can push branches to and open a draft PR/MR against —
  the fixture source makes the *ticket* disposable, not the code hosting
  (spec Assumptions).

## Scenario 1 — A fixture task starts a run, with zero external requests (US1 / FR-001–004, SC-001)

1. Start kestrel with the config above. Wait one poll cycle (or run
   `python -m app poll` for the dry-run listing first, to confirm
   `hello-fixture` appears as a `WorkItem` with `source="fixture-issue"`).
2. Wait for the scheduled check to pick it up.
   **Expect**: exactly one run appears, `source` internally `"fixture-issue"`
   (never surfaced to the API — same as today), `repo="you/sandbox-repo"`,
   and it begins refining. No request was made to any GitHub/Jira ticket
   endpoint for this task's read/comment/status steps — only the repo's
   code-hosting API (clone, branch push, PR open) is touched, same as any
   other source.
3. Edit `hello-fixture.json`'s `body` on disk while the run is in progress.
   **Expect**: the *current* run keeps the wording it already read (no
   mid-run reload); the change is only picked up the next time this task is
   used (this run's own rerun, or a future fresh pickup) — see Scenario 2.

## Scenario 2 — Rerun restarts immediately with edits picked up (US2 / FR-005,006, SC-002,004)

1. Let the run from Scenario 1 finish (any terminal status — failed,
   escalated, complete; per spec Assumptions, rerun works regardless of
   status).
2. Edit `hello-fixture.json`'s `title` or `body`.
3. Call `POST /api/workflows/{workflow_id}/rerun` (or click Rerun in the
   workflow panel sidebar).
   **Expect**: `200 OK` with a **new** `workflow_id`; the prior run's branch
   is gone from both the local mirror and the remote; the new run starts
   within seconds — no wait for `poll_interval_seconds` — and its refine
   step reads the *edited* title/body.

## Scenario 3 — Rerun is refused for GitHub/Jira runs (US3 / FR-007,008,009, SC-003)

1. Start (or use an existing) run whose task source is GitHub or Jira.
2. Confirm no Rerun button is shown in the workflow panel for that run
   (`WorkflowDetail.rerunnable == false`).
3. Call `POST /api/workflows/{workflow_id}/rerun` directly against that
   run's id (bypassing the UI).
   **Expect**: `403 Forbidden`, `{"detail": "rerun is not available for
   this workflow's task source"}` (see `contracts/rerun-endpoint.md`); the
   run is completely unchanged — branch intact, status unchanged, no
   dismissal touched.
4. Use the existing Abandon (`DELETE /{id}`) and Clean-up
   (`POST /{id}/cleanup`) actions on the same run.
   **Expect**: behavior identical to today — neither action ever contacts
   GitHub/Jira to modify the ticket (unchanged regression check, FR-009).

## Verification commands

```bash
# Backend
cd backend && uv run pytest tests/test_fixture_task_source.py \
  tests/test_fixture_poll.py tests/test_workflow_rerun.py -v

# Frontend
cd frontend && npm test -- useWorkflows

# Full gate (required before this feature is considered done)
task quality
```

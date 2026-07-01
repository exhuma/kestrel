# Design: GitHub issue → code workflow

Date: 2026-07-01
Status: Approved (design); implementation pending

## Context

agent-dispatcher can spawn a `claude` session, stream its events live, and
resume it with human input. That is a single agent run. This is the first
**workflow**: a fixed, human-in-the-loop pipeline that turns a GitHub issue
into a pull request through several ordered agent steps, each producing a
deliverable a human validates in the dispatcher before the run proceeds.

The goal is a genuine multi-step chain that exercises the tool's original
premise (plan → watch → refine → resume) end to end, while reusing the
existing session/streaming machinery rather than inventing a new execution
engine.

## Constraints (agreed)

- **No GitHub project or access token is available yet.** `GitHubClient` is
  written to the public GitHub REST API documentation and verified entirely
  with mocked `httpx` in unit tests. Its base URL and token are configurable
  so a real (or Enterprise) endpoint slots in later. Live GitHub verification
  is explicitly deferred until a repo + token exist.
- `GitService` (clone/branch/commit/push) is tested for real against a local
  bare git repository acting as the remote — no network, no GitHub.
- Single-user, in-memory state (consistent with sessions). Durable
  persistence is a deferred follow-up.

## Pipeline

Trigger: the user supplies a repo (`owner/name`) and an issue number.

1. **Fetch + prepare** — fetch the issue via the GitHub API; `GitService`
   clones the repo into a workspace and creates a branch
   (`dispatcher/issue-<n>`). If the fetched issue body already contains the
   refinement sentinel, the **Refine** step is skipped and the run starts at
   **Plan**.
2. **Refine** (interactive, read-only) — a `claude` session reads the issue +
   codebase and asks interview-style clarifying questions. After each agent
   turn the backend inspects the output: if it contains a refined issue inside
   the delimiter `<REFINED_ISSUE>…</REFINED_ISSUE>`, the step becomes
   `awaiting_approval` with that text as the deliverable; otherwise the output
   is treated as more questions and the step becomes `awaiting_input`. The
   human answers questions via **reply** (session resume), looping until the
   refined issue appears.
   - Deliverable: the **refined issue text** (editable before acceptance).
   - Gate: on approve, the backend PATCHes the GitHub issue body to the
     refined text **plus the sentinel** `<!-- agent-dispatcher:refined -->`.
3. **Plan** (read-only) — a fresh `claude` session plans from the refined
   issue.
   - Deliverable: the **plan**. Gate: approve / reject.
4. **Implement** — resumes the plan session in `acceptEdits` so the agent
   edits files in the clone.
   - Deliverable: the **git diff** of the branch. Gate: approve / reject.
5. **Open PR** — on implement approval, the backend commits, pushes the
   branch, and opens a **draft** pull request via the API
   (title from the issue, body referencing the issue).
   - Deliverable: the **PR URL**. Terminal state `done`.

Any step failure sets the run to `failed` with the error surfaced (not an
HTTP 500, since steps run in a background task). Reject at any gate ends the
run as `rejected`.

## Architecture

Reuses the existing `routers → services → storage` layering and the live
streaming from the session work. A workflow is an **orchestrator over
sessions**: each step is a `claude` subprocess spawned by the existing
`SessionRunner`, so step events stream into the same telemetry feed with no
new streaming code.

New units (each has one purpose, a clear interface, and is independently
testable):

- **`GitHubClient`** (`app/services/github.py`) — async `httpx` wrapper.
  - `get_issue(repo, number) -> Issue` — `GET /repos/{owner}/{repo}/issues/{n}`.
  - `get_default_branch(repo) -> str` — `GET /repos/{owner}/{repo}`, reads
    `default_branch` (used as the PR base).
  - `update_issue(repo, number, body)` — `PATCH …/issues/{n}` with `{body}`.
  - `create_pull_request(repo, head, base, title, body, draft=True) -> str`
    — `POST …/pulls`, returns `html_url`.
  - Headers: `Authorization: Bearer <token>`, `Accept:
    application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`.
  - Base URL + token from settings. Domain errors on non-2xx.
- **`GitService`** (`app/services/git.py`) — subprocess wrapper over `git`.
  - `clone(repo, dest)`, `checkout_branch(dest, branch)`,
    `commit_all(dest, message)`, `push(dest, branch)`.
  - Auth: for the `clone` and `push` commands (which reach the remote), the
    token is injected per-command via `git -c http.extraheader=...`, so it is
    never written into `.git/config`.
- **`WorkflowService`** (`app/services/workflows.py`) — the state machine.
  Owns a `WorkflowRun`, drives it through the pipeline in a **background
  task** (like the streaming runner), delegates step execution to
  `SessionRunner`, git to `GitService`, and GitHub to `GitHubClient`. Holds
  the refine done-signal extraction and sentinel logic.
- **`WorkflowRegistry`** (`app/storage/workflow_registry.py`) — in-memory
  store of runs (mirrors `SessionRegistry`).

### Data model

`WorkflowRun`:
- `id: str`
- `repo: str` (`owner/name`), `issue_number: int`, `issue_title: str`
- `base_branch: str` (repo default branch), `branch: str`
- `workspace: str` (clone path)
- `status: str` — a computed label from the current step's name and status
  (e.g. `refining`, `awaiting_refine_approval`, `implementing`,
  `opening_pr`), plus the terminal states `done | failed | rejected`
- `steps: list[WorkflowStep]`
- `pr_url: str | None`, `error: str | None`

`WorkflowStep`:
- `name: str` — `refine | plan | implement`
- `session_id: str | None` — the underlying session (for live events)
- `status: str` — `pending | running | awaiting_input | awaiting_approval |
  done | failed`
- `deliverable: str | None` — refined issue / plan / diff (markdown or text)

`awaiting_input` is unique to the interactive refine loop; the other steps use
`awaiting_approval` at their gate.

## API

All under `/api/workflows`. Domain exceptions map to explicit status codes via
handlers registered at app-factory time.

- `POST /api/workflows` `{repo, issue_number}` → `{workflow_id}`. Returns
  immediately; the run proceeds in the background.
- `GET /api/workflows` → list of run summaries.
- `GET /api/workflows/{id}` → full detail: status, steps (with `session_id`,
  `status`, `deliverable`), current `session_id`, `pr_url`, `error`.
- `POST /api/workflows/{id}/reply` `{text}` → answer the refine interview
  (valid only while refine is `awaiting_input`; resumes the refine session).
  Wrong state → `409`.
- `POST /api/workflows/{id}/approve` `{deliverable?}` → approve the current
  gate, optionally carrying an edited deliverable (e.g. the tweaked refined
  issue before it is written to GitHub). Advances refine → plan → implement →
  PR. Wrong state → `409`.
- `POST /api/workflows/{id}/reject` → cancel the run.
- Unknown id → `404` (`WorkflowNotFoundError`).

**Live events reuse `/api/sessions/{session_id}/events`** — the workflow
detail exposes the current step's `session_id`; the frontend streams that.

### Domain exceptions (new)

- `WorkflowNotFoundError` → 404.
- `InvalidWorkflowStateError` (reply/approve/reject in the wrong phase) → 409.
- Step/git/GitHub failures are recorded on the run as `status=failed` +
  `error`; `GitHubClient`/`GitService` raise typed errors the service catches.

## Frontend

A new **Workflows** surface reusing the Mission Control tokens and the
existing telemetry-feed component. A top-bar toggle switches between
*Sessions* and *Workflows*.

- **Left rail:** a "New workflow" form (repo `owner/name` + issue number) and
  a list of runs with status chips.
- **Main stage:** the selected run as a horizontal **step tracker**
  (`Refine · Plan · Implement · PR`) with per-step status; below it the
  **current step's live telemetry feed**, a **deliverable panel** (refined
  issue / plan / diff), and contextual controls — a **reply box** during
  refine `awaiting_input`, **Approve / Reject** at each gate, and the **PR
  link** when done.

Business types in `frontend/src/types/` mirror the workflow JSON shapes; keep
them in sync (per `contract.md`).

## Configuration & secrets

- `DISPATCHER_GITHUB_TOKEN` — GitHub token (required for GitHub calls).
- `DISPATCHER_GITHUB_API_BASE` — default `https://api.github.com`.
- Sourced via the existing pydantic `Settings`. `.env` stays gitignored; add a
  documented `.env.example`. The token is never committed and never persisted
  into `.git/config`.

## Testing

- **`GitHubClient`** — unit tests with a mocked `httpx` transport asserting
  method, URL, headers, and JSON body for `get_issue` / `update_issue` /
  `create_pull_request`, and parsing of documented response shapes. No live
  calls.
- **`GitService`** — tests against a real **local bare repo** as the remote:
  clone, branch, commit, push, and assert the pushed ref/content. Exercises
  real `git` with no network.
- **`WorkflowService`** — state-machine tests with fakes for the runner, git,
  and GitHub: happy path (refine → plan → implement → PR), sentinel skip,
  reject, and failure transitions. Refine done-signal extraction and sentinel
  append/detect are unit-tested directly.
- **Router** — endpoint tests with a mocked service asserting status codes
  (including 404 / 409) and payloads.
- **Streaming** — a mock `claude` (as used elsewhere) drives step event
  streaming so the reuse of session SSE is exercised.
- **Frontend** — vitest for the workflow composable/API client; build +
  `vue-tsc` clean.

## Build order

One spec, sequenced in the implementation plan:
1. Config + `.env.example`; domain exceptions.
2. `GitHubClient` (mocked-httpx tested).
3. `GitService` (local-bare-repo tested).
4. `WorkflowService` + `WorkflowRegistry` + step orchestration (fakes).
5. Routers + exception handlers.
6. Frontend Workflows surface.

## Out of scope (v1; iterate later)

Webhooks / auto-trigger, DB persistence, multi-user, retry or re-plan on
reject, incremental commits during implement, and merging the PR. Live GitHub
verification is deferred until a repo + token are available.

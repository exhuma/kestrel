# M-C · GitHub Ingestion & Repo Ops — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

> **STATUS: DRAFT (task-level).** Depends on M-B's work items and
> orchestrator. Before execution, expand each task to step-level
> TDD detail (superpowers:writing-plans) against the then-current
> codebase.

**Goal:** Real GitHub issues flow into the orchestrator via verified
webhooks (with polling reconciliation), and kestrel can act on
GitHub (comment, edit description, branch, PR) and on local clones
(worktree per issue).

**Architecture:** All deterministic, no LLM. `TaskSource` protocol
isolates source specifics; `GitHubSource` implements it over the
GitHub REST API with `httpx`. Webhook ingress verifies
`X-Hub-Signature-256` HMAC and dedups on the delivery id. A
`workspace` module manages one clone per repo and one `git worktree`
+ branch per work item.

**Tech Stack:** httpx (already a dev dep; promote to runtime),
hmac/hashlib stdlib, git CLI via asyncio subprocess.

## Global Constraints

Same as M-A, plus: GitHub token/webhook secret only via
`KESTREL_GITHUB_TOKEN` / `KESTREL_WEBHOOK_SECRET` (documented in
`.env.example`, never committed). New tables via Alembic only.

---

### Task 1: TaskSource protocol

**Files:**
- Create: `backend/app/sources/__init__.py`
- Create: `backend/app/sources/base.py`
- Test: `backend/tests/test_sources_base.py`

**Interfaces:**
- Produces: `TaskSource` protocol: `fetch_item(external_id) ->
  SourceItem`, `update_description(external_id, body)`,
  `post_comment(external_id, body)`,
  `open_pr(repo, branch, title, body, draft) -> str` (URL);
  `SourceItem` dataclass (`external_id`, `title`, `body`, `url`).

- [ ] Protocol + dataclass defined; typing-only test (a stub class
      satisfies the protocol).
- [ ] Commit.

### Task 2: GitHubSource

**Files:**
- Create: `backend/app/sources/github.py`
- Modify: `backend/app/config.py` (`github_token`, `github_api_url`
  with default `https://api.github.com`)
- Test: `backend/tests/test_github_source.py`

**Interfaces:**
- Consumes: `TaskSource` (Task 1).
- Produces: `GitHubSource(settings, client)` implementing the
  protocol; external ids are `"owner/repo#123"`. Injected
  `httpx.AsyncClient` so tests use `httpx.MockTransport` — no
  recorded network needed.

- [ ] fetch/update/comment/PR implemented against mocked
      transport, incl. 404 and 401 error mapping to domain errors.
- [ ] Commit.

### Task 3: Webhook ingress (HMAC + dedup)

**Files:**
- Create: `backend/app/ingestion/__init__.py`
- Create: `backend/app/ingestion/webhook.py`
- Create: `backend/app/routers/webhooks.py`
- Modify: `backend/app/persistence/tables.py` + migration
  (`webhook_delivery` table for dedup)
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_webhook.py`

**Interfaces:**
- Consumes: orchestrator intake (M-B service).
- Produces: `POST /api/webhooks/github` verifying
  `X-Hub-Signature-256` via `hmac.compare_digest`; on
  `issues.opened` / `issues.edited` creates-or-updates the work
  item and hands it to the orchestrator; replayed
  `X-GitHub-Delivery` ids are acknowledged but ignored.

- [ ] Bad/missing signature → 403 (constant-time compare).
- [ ] Duplicate delivery id → 200, no second work item.
- [ ] `issues.opened` fixture payload → work item in `intake`.
- [ ] Commit.

### Task 4: Poll reconciliation

**Files:**
- Create: `backend/app/ingestion/reconcile.py`
- Modify: `backend/app/main.py` (lifespan task)
- Modify: `backend/app/config.py` (`reconcile_interval_s`,
  `watched_repos: list[str]`)
- Test: `backend/tests/test_reconcile.py`

**Interfaces:**
- Produces: a periodic asyncio task listing recent open issues in
  `watched_repos` and creating any work item the webhook missed;
  same code path as webhook intake (dedup by
  `(source, external_id)`).

- [ ] One reconcile pass is a plain async function (testable
      without the timer); timer wraps it in `create_app` lifespan.
- [ ] Commit.

### Task 5: Workspace manager (clone + worktree)

**Files:**
- Create: `backend/app/workspace/__init__.py`
- Create: `backend/app/workspace/manager.py`
- Test: `backend/tests/test_workspace.py`

**Interfaces:**
- Produces: `WorkspaceManager.ensure_worktree(repo: str,
  work_item_id: int) -> Path` — clones the repo once under
  `workspace_root/repos/<owner>__<repo>`, then creates worktree +
  branch `kestrel/issue-<n>` under
  `workspace_root/worktrees/<work-item-id>`;
  `remove_worktree(work_item_id)`; `push(work_item_id)`.
  M-F runs implementation sessions with `cwd` = this worktree.

- [ ] Tested against a local bare fixture repo created in
      `tmp_path` (no network).
- [ ] Idempotent: second `ensure_worktree` call returns the same
      path without error.
- [ ] Commit.

## Verification

- `uv run pytest -v` green (all GitHub tests offline via
  MockTransport; git tests via local fixture repos).
- Manual E2E with a sandbox repo + tunnel (e.g. cloudflared):
  configure the webhook, open a real issue, confirm a work item
  appears in `intake`; stop the tunnel, open another issue, confirm
  reconciliation picks it up within one interval.
- Tick M-C in `kestrel-roadmap.md`.

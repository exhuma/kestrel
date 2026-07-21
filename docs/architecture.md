# Architecture

_System context as of 2026-07-05 (alpha). Design history and the backlog now
live in the [GitHub issue tracker](https://github.com/exhuma/kestrel/issues)._

Kestrel is a **single-user** tool that dispatches and monitors coding-agent
sessions from a web UI. One process serves both the API and (when packaged)
the built SPA.

## Components

| Component | Responsibility |
| --- | --- |
| **FastAPI backend** (`backend/app`) | HTTP API, session/workflow orchestration, SSE streaming |
| **Backend adapters** (`backend/app/backends`) | Dispatch targets behind one `Backend` protocol: `claude_cli`, `opencode`, `openai_compat` |
| **Persistence** (`backend/app/persistence`) | SQLite via SQLAlchemy, schema managed by Alembic |
| **SPA** (`frontend/`) | Vue 3 + Vuetify UI; in the image it is served same-origin by the backend |

## Key boundaries

- **The `Backend` protocol** (`backends/base.py`) is the seam everything above
  the adapters talks to. It exposes `start` / `resume` / `run_turn` /
  `terminate` and a `Capability` set (`TEXT`, `FILE_EDITS`, `TOOL_USE`). A
  step is served only by a backend whose capabilities are a superset of the
  step's requirement, so a plain LLM can serve a text step but not an
  `implement` step. Adapters never leak a tool's flags or output format
  upward.
- **A canonical event vocabulary** (`models.py`) normalizes each backend's
  native stream (claude's `stream-json`, opencode's SSE, an LLM's tokens)
  onto one timeline the UI consumes.
- **Server-sent events** carry that timeline to the browser live; the backend
  adds heartbeat/anti-buffering headers so the UI updates in real time.
- **Per-run git workspaces** under `KESTREL_WORKSPACE_ROOT` isolate each
  session's file edits and stay browsable on the host.

## External dependencies

The image bundles only the `claude` CLI (plus Node and git). `opencode` and
self-hosted LLMs are **external backing services addressed by URL** — started
separately and reached over HTTP, never bundled into the image. This keeps
the image small and lets a deploy attach or swap backends purely by config.

## Data & auth

- **State** lives in SQLite on the `/data` volume; migrations run on every
  container start (idempotent).
- **Agent auth** is inherited from the host `claude` login (seeded read-only
  into the container), never re-implemented by kestrel. The only secret
  kestrel itself consumes is an optional `KESTREL_GITHUB_TOKEN`.

## Design trade-offs

- **Single-user, no auth.** Deliberate for the alpha: kestrel is a personal
  tool bound to loopback. Multi-user/authn is out of scope. One exception:
  the GitHub webhook endpoint (`POST /api/github/webhook`) is intended to
  face the network so GitHub can deliver events; its authenticity gate is an
  HMAC signature, not loopback binding (see the constitution's access model).
- **Ingestion is a seam, and the ports are now extracted.** GitHub ingestion
  (webhook + reconciliation) and **Jira ingestion (poll-only, feature 003)** both
  feed one source-neutral entry point (`ingestion.maybe_start_run`, keyed on a
  `task_ref`). The load-bearing axis — *task source* (the ticket) vs *code host*
  (the repo) — is now realized as two protocols in `app/ports.py`: `TaskSource`
  (read/comment/attach/publish/deep-link) and `CodeHost` (default branch, clone
  remote, open a merge/pull request). GitHub implements both roles; **Jira**
  implements `TaskSource` and delegates the `CodeHost` role to a configured,
  **self-hostable** git host (GitLab reference; Gitea/Forgejo the same port) —
  kestrel is sovereign by design, so a Jira-resolved repo can live on an on-prem
  GitLab. The outbound `Notifier` is source-dispatching (`TaskSourceNotifier`),
  posting thin gate/escalation comments to *the run's own* ticket. Jira is
  poll-only, so it adds **no** off-loopback endpoint (no constitution amendment);
  the entry point is shaped so a future Jira webhook is one added caller.
- **One unified, source-agnostic workflow.** Every run — Jira, GitHub, or manual
  — traverses the identical `refine → PRD approval → design → code → verify →
  change request` sequence (`services/workflows.py`). The single human gate is
  PRD approval; design/code/verify run **gatelessly**. The **verifier**
  adjudicates the implementation against the PRD/design weighing measurable
  **evidence** (the project's checks run in the isolated worktree, `services/
  checks.py`); a failing check forces a reject, the loop is bounded by
  `max_verify_iterations`, and it **escalates** to the ticket on exhaustion. The
  task source is only the human↔agent boundary — the process behind it is the
  same, so the system is predictable.
- **CLI subprocess for claude, HTTP for the rest.** Reuses the user's
  existing Claude login and MCP/plugin config without an SDK or API key, at
  the cost of depending on the CLI's stream format (isolated in one adapter).
- **SQLite.** Right-sized for a single user; the `KESTREL_DATABASE_URL` seam
  leaves room to attach another database later.

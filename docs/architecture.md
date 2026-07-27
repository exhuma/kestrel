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
  (webhook + reconciliation) and **Jira ingestion (poll-only, feature 003)**
  both feed one source-neutral entry point (`ingestion.maybe_start_run`, on a
  `task_ref`). The load-bearing axis — *task source* (the ticket) vs *code host*
  (the repo) — is now realized as two protocols in `app/ports.py`: `TaskSource`
  (read/comment/attach/publish/deep-link) and `CodeHost` (default branch, clone
  remote, open a merge/pull request). GitHub implements both roles; **Jira**
  implements `TaskSource` and delegates the `CodeHost` role to a configured,
  **self-hostable** git host (GitLab reference; Gitea/Forgejo the same port) —
  kestrel is sovereign by design, so a Jira-resolved repo can live on an on-prem
  GitLab. The outbound `Notifier` is source-dispatching (`TaskSourceNotifier`),
  posting thin gate/escalation comments to *the run's own* ticket. Jira is
  poll-only, so it adds **no** off-loopback endpoint (no amendment); the entry
  point is shaped so a future Jira webhook is one added caller.
- **One unified, source-agnostic workflow.** Every run — Jira, GitHub, or manual
  — traverses the identical `refine → PRD approval → design → code → verify →
  change request` sequence (`services/workflows.py`). The single human gate is
  PRD approval; design/code/verify run **without human gates**. The **verifier**
  adjudicates the implementation against the PRD/design weighing **evidence**
  it observes by exercising the running, modified project itself (see below);
  a failing observation forces a reject, the loop is bounded by
  `max_verify_iterations`, and it **escalates** to the ticket on exhaustion. The
  task source is only the human↔agent boundary — the process behind it is the
  same, so the system is predictable.
- **Behavioral verify evidence, grounded in real, observed behaviour.** The
  `design` step classifies the project's user-facing boundary — HTTP API, web
  UI, both, or none (`run.boundary`, from a `<BOUNDARY>` tag) — once per run.
  When a boundary exists, verify runs a **tool-enabled explore turn** first,
  instructed to launch and exercise the running, modified project for real
  (real HTTP requests for an HTTP boundary, browser-driven interaction for a
  UI boundary) using whatever tools the operator's own backend already
  provides (Bash, MCP — Playwright or otherwise). Kestrel owns no HTTP client
  or browser-automation code itself; it delegates entirely to the verifying
  agent's own capabilities, trusting the operator's environment the same way
  the `code` step already does. A second, disciplined **verdict turn** then
  resumes that same session back in `plan` mode with no new tools — preserving
  the single-shot `<VERDICT>` reliability the original design already depended
  on — and self-reports its observations as part of that same verdict, so the
  failing-observation invariant applies to whatever it found. This is
  deliberately verify's *only* evidence source: durable, deterministic checks
  (tests, lint) are the coder's TDD responsibility (`CODE_PROMPT`), not
  something verify re-runs — blending the two would let a purely technical
  failure (a coder that didn't test its own work) masquerade as a behavioral
  one, undermining the "judge like a stakeholder, not a code reviewer"
  principle below. Requirement conformance is the only thing that can force a
  reject; code-quality/documentation observations are advisory feedback only.
  Each run's verify rounds are recorded as a committed `verify-report.md`
  audit-trail artifact (same `.kestrel/` handover mechanism as `prd.md`/
  `design.md`) — history for a human, never a regression contract a later
  run's verify step is obligated to satisfy.
- **File-based step handover (`.kestrel/`).** The steps share one worktree, so a
  step's artifacts pass to the next as *files* under
  `.kestrel/<YYYY-MM-DD>-<serial>/` (`prd.md`, `design.md`) — spec-kit's
  `.specify/` in spirit. A file-capable backend (claude, opencode) is pointed at
  the file so a large PRD/design never bloats its prompt; a text-only LLM, which
  cannot read the worktree, still gets the content inlined. The artifacts are
  committed with the change (they appear in the PR/MR and accumulate in the repo
  under dated folders) but are excluded from the operator-facing code diff
  (`code_step.deliverable`).
- **The coder commits, the verifier never sees a diff.** Coder and verifier
  share the same worktree, so there is no need to serialize a diff between
  them: the coder commits its own work each round (`WIP:`-prefixed when
  unsure) via an instruction in `CODE_PROMPT`, and kestrel commits on its
  behalf as a safety net if the tree is still dirty afterwards — never
  blindly trusting the model to have committed correctly. The verifier judges
  the PRD/design against the running, checked-out tree and what it observes
  by exercising it live; it is never shown diff text. `code_step.deliverable`
  (the UI's diff view) is instead the cumulative diff since the run's branch
  point, computed on kestrel's side from git history.
- **CLI subprocess for claude, HTTP for the rest.** Reuses the user's
  existing Claude login and MCP/plugin config without an SDK or API key, at
  the cost of depending on the CLI's stream format (isolated in one adapter).
- **SQLite.** Right-sized for a single user; the `KESTREL_DATABASE_URL` seam
  leaves room to attach another database later.

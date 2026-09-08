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
  Feature 013 (feedback intake) adds three more event types to that same
  endpoint — `issue_comment`, `pull_request_review`, and
  `pull_request_review_comment` — rather than a second endpoint; they carry
  the identical HMAC gate.
- **Feedback intake: a marked ticket/review comment steers a run in flight
  (feature 013).** A run is never a fire-and-forget dispatch: once started,
  a comment carrying the configured trigger marker (`feedback_marker`,
  default `@kestrel`) redirects it, on either a GitHub webhook delivery or
  the poll backstop every task source shares (`FeedbackPollService`).
  Every transport funnels through one convergence point,
  `FeedbackIntakeService.intake` — marker gate → author/bot guard → claim
  (dedup on `feedback_item.external_id`) → route to the newest run for the
  ticket (or, for a PR review comment, the run whose `pr_number` matches) →
  persist `queued` → best-effort acknowledge (a reaction, where the source
  supports one). `FeedbackDispatcher` then branches on that run's *current*
  status: parked at a human gate → applied immediately, exactly like a UI
  reject-with-feedback; mid-step with no open gate → left `queued` for
  `drain_feedback` to fold in at the next round/step boundary the driver
  reaches on its own (never interrupting a turn in flight); `escalated` →
  retried from the base branch with the feedback as guidance; `done` → the
  same PR is resumed if still open, else a linked successor run starts
  (`WorkflowRun.parent_run_id`). Self-feedback-loops (kestrel reacting to
  its own comments) are guarded three ways at once — no fixed template
  kestrel writes ever contains the marker, an author denylist plus
  GitHub's bot-account flag, and the `external_id` primary key that caps
  any breach of the first two guards at exactly one iteration. See
  `docs/setup-github-workflow.md`, `docs/setup-jira-workflow.md`, and
  `docs/setup-fixture-workflow.md` for the per-source operator picture
  (configuration, acknowledgment behaviour, revive-vs-successor).
- **Ingestion is a seam, and the ports are now extracted.** GitHub ingestion
  (webhook + reconciliation) and **Jira ingestion (poll-only, feature 003)**
  both feed one source-neutral entry point (`ingestion.maybe_start_run`, on a
  `task_ref`). The load-bearing axis — *task source* (the ticket) vs *code host*
  (the repo) — is now realized as two protocols in `app/ports.py`: `TaskSource`
  (read/comment/attach/publish/deep-link/**display-label**, feature 009) and
  `CodeHost` (default branch, clone remote, open a merge/pull request).
  GitHub implements both roles; **Jira**
  implements `TaskSource` and delegates the `CodeHost` role to a configured,
  **self-hostable** git host (GitLab reference; Gitea/Forgejo the same port) —
  kestrel is sovereign by design, so a Jira-resolved repo can live on an on-prem
  GitLab. The outbound `Notifier` is source-dispatching (`TaskSourceNotifier`),
  posting thin gate/escalation comments to *the run's own* ticket. Jira is
  poll-only, so it adds **no** off-loopback endpoint (no amendment); the entry
  point is shaped so a future Jira webhook is one added caller. A third
  `TaskSource`, **fixture (feature 008)**, is file-backed: one JSON task per
  file under a configured `fixtures_dir`, for disposable local testing/retry
  without touching a real GitHub issue or Jira ticket — it reuses an existing
  `CodeHost` rather than adding a fourth one. Every `TaskSource` now also
  declares a `visibility()` capability (`"public"` | `"private"`): GitHub and
  Jira are `"public"` — their tickets are externally shared and only ever
  move forward in time; fixture is `"private"`. The **rerun** action (abandon
  a run, delete its branch, and immediately restart it against the same
  task) is permitted only when `visibility() == "private"`, so it can never
  be exposed for a GitHub- or Jira-sourced run (see the constitution's access
  model, amendment 1.4.0).
- **One unified, source-agnostic workflow.** Every run — Jira, GitHub, or
  fixture — traverses the identical `describe → refine → gap_analysis →
  design → code → verify → change request` sequence
  (`services/workflows/driver/`). There is no hand-entered run: a run exists
  because a task source produced a task. **Two** human gates open the
  pipeline: `describe` restates kestrel's understanding of the task in plain
  language and parks for the requester to confirm or amend it, before any
  clarifying question is asked; `refine`'s interview is then restricted to
  non-technical, requestor-altitude profiles only (`requester`/`pm`/`uiux`),
  producing a business-only, go/no-go requirements document — the PRD
  approval gate. Once approved, `gap_analysis` runs **gatelessly** (feature
  012): technical-altitude profiles (`developer`/`infosec`/`dba`/`architect`/
  `ops`/`qa`) analyze the approved requirements, producing an
  architecture/technical-decision record and one or more independent,
  self-contained follow-up tasks — checked by a completeness self-review
  turn before publishing — which are published back to the task source as
  subdivisions of the original ticket, without themselves satisfying that
  source's ingestion trigger (so publishing them starts no new run). The
  original run then ends (`status = "decomposed"`); it never itself reaches
  `design`/`code`/`verify`. A promoted follow-up task, recognized via a
  second sentinel marker in its body (`SUBTASK_SENTINEL`, alongside the
  existing "already refined" `SENTINEL`), skips `describe`/`refine`/
  `gap_analysis` entirely and starts at `design` — it is already scoped and
  technical. From `design` onward, every run — original or follow-up — runs
  **without human gates**. The **verifier** adjudicates the implementation
  against the PRD/design weighing **evidence** it observes by exercising the
  running, modified project itself (see below); a failing observation forces
  a reject, the loop is bounded by `max_verify_iterations`, and it
  **escalates** to the ticket on exhaustion. The task source is only the
  human↔agent boundary — the process behind it is the same, so the system is
  predictable.
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
  `.kestrel/<YYYY-MM-DD>-<serial>/` (`prd.md`, `technical-analysis.md`,
  `design.md`) — spec-kit's
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
- **Little to no persistence — nothing kestrel-caused reaches a commit.**
  Kestrel's own state lives in source code and task-source items only, so a
  run must be handoff-able to a human at any moment with nothing hidden in
  kestrel-side state. This extends to the worktree itself: a work-time
  artifact caused purely by kestrel's own dispatch (e.g. the operator's
  Playwright MCP server writing its cache into the worktree because
  kestrel points its `cwd` there during the verify step's explore turn)
  must never leak into a commit or the PR. Known cases are seeded once,
  deterministically, into the run's mirror's shared `info/exclude`
  (`GitService._write_kestrel_excludes`) — `git add -A` (used throughout
  the commit path, and by the coding agent's own instructed commit) already
  honours it, so no commit-path call site needs to special-case anything.
  For a case kestrel doesn't yet know about, the coding agent is instructed
  (`_COMMIT_INSTRUCTION`, `prompts.py`) to triage any untracked file itself
  before committing: material to the change → commit it; the *project's*
  own toolchain artifact → the tracked `.gitignore`; a work-time artifact
  of kestrel's own dispatch → `.git/info/exclude`, never `.gitignore`,
  since it is not the project's concern.
- **CLI subprocess for claude, HTTP for the rest.** Reuses the user's
  existing Claude login and MCP/plugin config without an SDK or API key, at
  the cost of depending on the CLI's stream format (isolated in one adapter).
- **SQLite.** Right-sized for a single user; the `KESTREL_DATABASE_URL` seam
  leaves room to attach another database later.

# Architecture

_System context as of 2026-09-24 (alpha), after spec
[026-autonomous-work-board](../specs/026-autonomous-work-board/spec.md)'s
Phase 10 "clean break": the old fixed six-step workflow driver (describe →
refine → technical_analysis → design → code → verify) and its
`WorkflowPanel.vue` frontend were deleted outright, with no data migration,
and replaced by the event-driven **work board** described below. Design
history and the backlog live in the
[GitHub issue tracker](https://github.com/exhuma/kestrel/issues)._

Kestrel is a **single-user** tool that dispatches and monitors coding-agent
sessions from a web UI. One process serves both the API and (when packaged)
the built SPA.

## Components

| Component | Responsibility |
| --- | --- |
| **FastAPI backend** (`backend/app`) | HTTP API, session/board orchestration, SSE streaming |
| **Backend adapters** (`backend/app/backends`) | Dispatch targets behind one `Backend` protocol: `claude_cli`, `opencode`, `openai_compat` |
| **Persistence** (`backend/app/persistence`) | SQLite via SQLAlchemy, schema managed by Alembic |
| **SPA** (`frontend/`) | Vue 3 + Vuetify UI; in the image it is served same-origin by the backend |

## Key boundaries

- **The `Backend` protocol** (`backends/base.py`) is the seam everything above
  the adapters talks to. It exposes `start` / `resume` / `run_turn` /
  `terminate` and a `Capability` set (`TEXT`, `FILE_EDITS`, `TOOL_USE`). A
  board specialist is served only by a backend whose capabilities are a
  superset of its `required_abilities`, so a plain LLM can serve a
  text-only role but not `coder`. Adapters never leak a tool's flags or
  output format upward.
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

## The work board (spec 026)

Replacing the old fixed driver, an accepted task becomes one **Workflow**
aggregate owning a graph of typed **Work Cards** — there is no fixed step
sequence. See `specs/026-autonomous-work-board/data-model.md` for the full
entity reference; this is the operator-relevant shape:

- **Work Card.** A single policy-governed unit of work with a closed `kind`
  vocabulary (`understanding_gate`, `refinement_gate`, `prd_gate`,
  `decomposition_gate`, `security_review`, `analysis`, `design`,
  `implementation`, `verification`, `reconciliation`, `coordinator_review`)
  and a universal state lifecycle: `ready → claimed →
  {waiting_dependency|awaiting_human|review|quarantined} →
  {done|failed|cancelled}`. A **Card Relation** is a directed
  `dependency`/`reconciliation`/`supersedes` edge; only `dependency` edges
  gate readiness.
- **Claims and leases.** A specialist claims one `ready` card at a time
  (`ClaimLease`, time-bounded, `board_claim_lease_seconds`). A
  write-permission card additionally needs a per-repository
  `WorkspaceLease` (`board_workspace_lease_seconds`) so only one writer can
  touch a given repo at once — read-only cards may run concurrently, up to
  `board_max_parallel_read_cards`. A background sweep
  (`board_recovery_interval_seconds`) reclaims expired leases and applies
  each card's bounded retry/reassign/escalate policy.
- **Handoff artifacts.** A card's accepted output is retained as an
  immutable, versioned `HandoffArtifact` (content-addressed under
  `board_artifacts_root`), with explicit pinned-revision input provenance
  and a `project_material` flag — set only when the artifact belongs in the
  eventual code change, so orchestration-only output never leaks into a
  commit.
- **Specialists** (`specialists/<role>/manifest.toml` + `prompt.md`,
  loaded from `specialists_root`): `requester`, `pm`, `uiux`, `developer`,
  `infosec`, `dba`, `architect`, `ops`, `qa` (read-only `analysis`/`design`
  work), `coordinator` (proposes, never claims), `coder` (the **only** role
  with a repository write lease), `verifier` (validates an implementation
  against its approved scope, exercising the change directly rather than
  re-running the coder's own checks), and `input-security` (quarantine
  classification). Each manifest's `model_policy` routes that role to a
  backend — `"default"` for `default_session_backend`, or a specific
  `[[backends]]` id — capability-checked against the role's
  `required_abilities` (`app/policy.py`). See [Backends](backends.md).
- **The coordinator** is event-driven, not polling: every committed board
  mutation wakes it in the background for the affected workflow
  (`BoardService`'s `on_mutation` hook). It proposes bounded, structured
  actions (`create_card` / `transition_card` /
  `create_reconciliation_card`) which are validated against deterministic
  policy and only then applied — it never mutates board state directly, and
  a rejected proposal is still recorded in the append-only `BoardEvent`
  ledger. A specialist may likewise propose follow-up work, but only the
  coordinator turns a proposal into a card.
- **Human gates.** `understanding_gate`/`refinement_gate`/`prd_gate`/
  `decomposition_gate` cards are never claimed by a specialist — only an
  operator resolves them, via `POST
  /api/board/workflows/{id}/cards/{id}/interventions` (`resolve_gate`).
  Approval cascades ready-dependent cards; rejection cancels only the cards
  that actually depended on that gate, never the whole workflow. Other
  interventions (`retry`, `cancel`, `reassign`,
  `request_coordinator_review`) are optimistic-concurrency-checked against
  `expected_revision`.
- **Quarantine — the fail-closed untrusted-input boundary.** Every external
  or human-supplied input (a task body, a gate answer, a direct session
  prompt) passes through `QuarantineService` before it can reach an agent, a
  workflow transition, or a task-source write. Oversized content
  (`board_input_max_bytes`), a missing/incapable `input-security`
  specialist, and any malformed or timed-out classification
  (`board_input_security_timeout_seconds`) all fail **closed** into a
  `security_review` card — nothing here ever treats an unclear result as
  safe. An operator releases or discards a pending review via `POST
  /api/board/security-reviews/{id}/resolve`; suspect content itself never
  enters board events, logs, or summaries.

**API surface** (all under `/api/board`, SSE-streamed as full-snapshot
replacement, never incremental patches): `GET /workflows` (collection
summary) and `GET /workflows/events` (its SSE stream); `GET
/workflows/{id}/board` (one workflow's full snapshot: cards, relations,
`revision`) and `GET /workflows/{id}/board/events`; `GET
/workflows/{id}/cards/{id}`; `POST
/workflows/{id}/cards/{id}/interventions`; `POST
/security-reviews/{id}/resolve`. See
`specs/026-autonomous-work-board/contracts/board-api.md`.

**Frontend.** `WorkBoard.vue` is the app's default view: a workflow list
plus a card-state-grouped list layout and a lazy graph layout
(`WorkflowGraph.vue`, Vue Flow), with `WorkCardDetail.vue` for one card and
its intervention actions. `useBoard.ts` wraps the API above. The old
per-run session panel remains reachable as a secondary debug view.

### Current gap: no task-source write-back or delivery yet

Everything above through gate/intervention resolution is live, and so is
the automatic specialist dispatch loop (spec 026 T034):
`app/services/board/bootstrap.py`'s `_trigger_scheduling` fires on every
committed board mutation, wakes the coordinator for one planning turn, then
calls `app/services/board/dispatch_ready.py::dispatch_ready_work`, which
tries a claim→turn→accept cycle for every non-coordinator role in the
roster. A `ready` card is now genuinely claimed, turned, and (on success)
accepted into `review`/`done` without any operator action — see
`tests/test_board_scheduling.py::TestDispatchReadyWork`.

A `read_only`/`write` card also gets a real workspace (spec 026 T041):
`app/services/board/workspace.py::WorkspaceService` provisions a per-repo
shared bare mirror plus one worktree per workflow, cut from it on demand
and reused (never reset) across a workflow's turns. A `write` card
additionally dispatches with `permission_mode="acceptEdits"`, so the
`coder` role can now genuinely read and edit files — its prompt instructs
it to commit its own work locally. See `tests/test_board_dispatch_workspace.py`.

**As of 2026-09-26, a `verification` card's result is also routed** (spec
026 T051): `app/services/board/verification.py::route_verifier_result`
parses the verifier's `<VERIFIER_FINDINGS>` block and creates one follow-up
card per finding — a `nonconformance`/`verification_gap` finding becomes a
new, immediately-ready `implementation` card for `coder` (internal
remediation, FR-027); an `ambiguity`/`requirement_conflict`/
`infeasibility`/`policy_risk` finding, or a result that fails to parse at
all, becomes a `coordinator_review` card that no specialist ever claims
(escalation, FR-028, fail closed). Every card is still created only through
`CoordinatorService.apply_actions` (FR-006). See
`tests/test_board_verification.py`.

**Deliberately still out of scope**: kestrel never pushes a coder's
commits or opens a change request, for either an initial implementation
or a verified remediation. Nothing currently decides "verification
passed, therefore deliver" — a clean verification result (empty findings)
creates no follow-up card at all, so the loop has no explicit "done, ship
it" signal yet. This is now the most important remaining gap (tasks.md
T067-T069, which also covers the rest of task-source write-back below).

**As of 2026-09-26, one of the five milestone kinds actually posts** (spec
026 T067, partial): `app/services/board/write_back.py::post_projection`
plans (via `projections.py`), posts via `TaskSource.post_comment()`, and
resolves exactly one projection, idempotent by key and never raising on a
post failure (recorded as retryable instead). Wired for **gate decisions
only**: resolving a human gate now posts `"Gate approved: <title>"` (or
`rejected`) back to the workflow's task source — see
`tests/test_board_write_back.py` and `bootstrap.py::schedule_gate_projection`.

What is **still not** wired up — tracked as follow-on work (spec 026
`tasks.md`'s Status section has the authoritative, per-task detail) — an
operator should not expect today:

- **Delivery: pushing a coder's verified work, or opening a change
  request.** A coder's commits stay local to its worktree even after a
  clean verification. Also not built: CI-pipeline-specific evidence/repair
  cards (tasks.md T052) — distinct from T051's verifier-finding routing,
  which covers a verifier's own findings (code review/local test run
  style) regardless of any CI system.
- **Write-back for anything except a resolved gate.** The other four
  FR-033 milestone kinds — escalation, approved-artifact, child-work,
  delivery — are not yet wired to `post_projection`, even though a
  `coordinator_review` card (escalation) is already created in two places
  (T051's verifier routing, and an operator's own "request coordinator
  review" intervention). In practice this still means: no status labels
  or Jira transitions are applied as a workflow progresses
  (`app/notifications.py`'s own docstring: "nothing currently produces a
  Notification row"); no `hooks_dir` executable is ever invoked (only the
  startup audit-log pass runs); no comment-based feedback steering (the
  old `@kestrel` marker mechanism was deleted with
  the driver and has no board-domain replacement); no decomposition is
  published back to the task source as child tickets; the optional
  translation backing service has no caller; and there is no **rerun**
  action (the endpoint that implemented it was deleted along with the
  fixed driver's router — see the constitution's access-model third
  constraint) and no **cleanup** action.
- Practically, this means a configured GitHub/Jira/local source today
  creates a board **Workflow** and its initial cards on a qualifying task
  (after quarantine screening); specialist cards then progress
  automatically, including a `coder` role committing real file edits to its
  own local worktree branch, and human gates/interventions still happen
  only in the Kestrel web UI. None of it is ever reported back to the
  ticket itself, and no coder's commits ever leave their local worktree —
  the operator has to look at Kestrel, not the source or a PR, to see
  progress.

## Design trade-offs

- **Single-user, no auth.** Deliberate for the alpha: kestrel is a personal
  tool bound to loopback. Multi-user/authn is out of scope. One exception:
  the GitHub webhook endpoint (`POST /api/github/webhook`) is intended to
  face the network so GitHub can deliver events; its authenticity gate is an
  HMAC signature, not loopback binding (see the constitution's access model).
  The endpoint currently handles only the `issues` event (label-trigger
  ingestion and child-issue lifecycle observation) — the `issue_comment` /
  `pull_request_review` / `pull_request_review_comment` handling the old
  feedback-intake subsystem added was removed with the fixed driver (see
  "Current gap" above) and carried no separate access-model exception of its
  own. Kestrel still identifies every comment it writes with a configurable
  `[kestrel:posted]` sentinel by default, independent of feedback intake.
- **Ingestion is a seam, and the ports are extracted.** GitHub ingestion
  (webhook + reconciliation), **Jira ingestion** (poll-only), and a
  file-backed **local** source all feed one source-neutral entry point
  (`ingestion.maybe_start_run`, on a `task_ref`) that now creates a board
  workflow rather than a driver run. The load-bearing axis — *task source*
  (the ticket) vs *code host* (the repo) — is realized as two protocols in
  `app/ports.py`: `TaskSource` (read/comment/attach/deep-link/
  display-label) and `CodeHost` (default branch, clone remote, open a
  merge/pull request). GitHub implements both roles; **Jira** implements
  `TaskSource` and delegates the `CodeHost` role to a configured,
  **self-hostable** git host (GitLab reference; Gitea/Forgejo the same
  port) — kestrel is sovereign by design, so a Jira-resolved repo can live
  on an on-prem GitLab. Jira is poll-only, so it adds **no** off-loopback
  endpoint. The local source uses recursive task folders with
  root-contained `task.json`, publishing a branch to a local bare
  repository without a change request or review. Every `TaskSource`
  declares a `visibility()` capability (`"public"` | `"private"`): GitHub
  and Jira are `"public"` — their tickets are externally shared and only
  ever move forward in time; local tasks are `"private"`. This capability
  is snapshotted onto every board workflow at ingestion time; it currently
  has no consumer (see "Current gap" above for rerun/cleanup, its intended
  use).

- **CLI subprocess for claude, HTTP for the rest.** Reuses the user's
  existing Claude login and MCP/plugin config without an SDK or API key, at
  the cost of depending on the CLI's stream format (isolated in one adapter).
- **SQLite.** Right-sized for a single user; the `KESTREL_DATABASE_URL` seam
  leaves room to attach another database later.
- **Source health is checked, not persisted.** Whether each configured
  `TaskSource`/`CodeHost` adapter is currently reachable and authenticated
  (feature 014) is a `check_health()` capability on the existing ports —
  a single cheap, ticket-independent, authenticated read per adapter (e.g.
  GitHub/GitLab `GET /user`, Jira `GET /myself`) — never a new port, and
  never more than "healthy"/"unhealthy" to the UI: the underlying cause
  (network vs. auth) is deliberately not surfaced, only logged
  server-side. Status lives entirely in memory (`HealthStore`), re-derived
  by a background cycle every `health_check_interval_seconds` plus an
  on-demand manual refresh — a value from before a restart is not more
  trustworthy than "unknown", so nothing is persisted. Displayed as a
  persistent per-source indicator in the app bar (pushed over SSE, the
  same `list()`-plus-bus pattern as the notification center), so a
  misconfiguration is visible immediately instead of only surfacing later
  as a failed run.

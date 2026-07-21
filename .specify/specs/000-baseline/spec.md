# Feature Specification: Baseline — kestrel as implemented

**Feature Branch**: `000-baseline`

**Created**: 2026-07-21

**Status**: Baseline (describes shipped behavior, not proposed work)

**Input**: Reverse-engineered from `docs/architecture.md`, `contract.md`, and the
backend/frontend source as of this commit. This document is a *descriptive*
baseline: it records what the system does today so that future specs can state
changes as deltas against it. Where behavior is a deliberate, contract-recorded
deviation or a known quirk, it is called out rather than idealized.

## User Scenarios & Testing *(mandatory)*

Kestrel is a **single-user** tool (bound to loopback, no authentication) that
dispatches coding-agent sessions and monitors them live from a web UI. The
journeys below are ordered by how central they are to that purpose.

### User Story 1 - Dispatch and monitor an ad-hoc agent session (Priority: P1)

The operator submits a prompt from the UI. Kestrel spawns a coding-agent
session in a fresh per-run workspace and streams the agent's activity —
assistant text, tool calls, tool results, thinking, and the terminal result —
back to the browser in real time. The operator can send a follow-up prompt to
the same session (resume), list past sessions, and abandon a session.

**Why this priority**: This is the product's core loop. With only this story
implemented, kestrel is already a usable single-user agent dispatcher.

**Independent Test**: `POST /api/sessions` with a prompt, open the session's
SSE stream, and observe canonical events arriving and ending with a `result`
event; then `POST /api/sessions/{id}/resume` and observe further events on the
same session; then `DELETE /api/sessions/{id}` and observe the session gone
from `GET /api/sessions`.

**Acceptance Scenarios**:

1. **Given** a running backend, **When** the operator POSTs a prompt to
   `/api/sessions`, **Then** a `session_id` is returned once the agent reports
   it, a per-run workspace directory is created, and the agent subprocess/turn
   begins producing events.
2. **Given** a session that exists, **When** the operator opens
   `GET /api/sessions/{id}/events`, **Then** all previously recorded events are
   replayed in order and then live events stream in, with keepalive heartbeats
   during idle periods.
3. **Given** a session that reached its terminal result, **When** its status is
   read via `GET /api/sessions`, **Then** it reads `idle` (it was `running`
   while active).
4. **Given** an existing session, **When** the operator resumes it with a new
   prompt, **Then** the session returns to `running`, reuses the same
   workspace, and appends new events to the same record.
5. **Given** an existing session, **When** the operator deletes it, **Then** any
   live subprocess is killed and the record and its events are removed from the
   store.

---

### User Story 2 - Turn a GitHub issue into a draft pull request (Priority: P2)

The operator points kestrel at a `repo` + `issue_number`. Kestrel clones the
repo into a per-run workspace, runs a profile-aware clarifying interview to
refine the issue, writes the refined issue back to GitHub, plans an approach,
implements the change, and opens a **draft** pull request — pausing at human
approval gates between stages.

**Why this priority**: This is the flagship higher-order workflow, but it
depends on the session-dispatch loop (Story 1) and on GitHub credentials, so it
is secondary to the core loop.

**Independent Test**: With `KESTREL_GITHUB_TOKEN` set, `POST /api/workflows`
with a real `{repo, issue_number}`, drive the run through its approval gates via
the `approve`/`answers` endpoints, and observe a `pr_url` and `done` status,
with a draft PR created on GitHub.

**Acceptance Scenarios**:

1. **Given** a repo and issue number, **When** the operator creates a workflow,
   **Then** a run is created with fixed steps `refine` → `plan` → `implement`,
   a branch `kestrel/issue-{n}`, and a workspace under the workspace root; the
   run then clones the repo and checks out the branch.
2. **Given** the refine stage, **When** the clarifying interview needs input,
   **Then** the run enters `awaiting_refine_input` and presents a structured
   questionnaire; submitted answers advance the interview round.
3. **Given** a refined issue draft, **When** the operator approves the refine
   gate, **Then** the refined text (with a `<!-- kestrel:refined -->` sentinel)
   is written back onto the GitHub issue and the run proceeds to planning.
4. **Given** an issue whose body already carries the refined sentinel, **When**
   a workflow is created for it, **Then** the refine stage is skipped.
5. **Given** an approved plan, **When** the implement stage produces a non-empty
   diff and the operator approves it, **Then** kestrel commits, pushes the
   branch, and opens a **draft** PR whose body closes the issue, storing the
   PR URL and ending the run `done`.
6. **Given** the implement stage produces no diff, **When** the agent returns
   questions instead, **Then** the run enters `awaiting_implement_input` and
   waits for a free-text reply before retrying.
7. **Given** any approval gate, **When** the operator rejects with a refinement
   prompt, **Then** the stage regenerates; rejecting without a prompt ends the
   run `rejected`. Deleting a run drops all local work and never touches GitHub.

---

### User Story 3 - Dispatch to alternate backends per step (Priority: P3)

The operator configures additional backends (a separately-run `opencode serve`,
or a self-hosted OpenAI-compatible LLM reached by URL) and maps workflow steps
to them. Kestrel routes each step to its configured backend, refusing any
mapping whose backend lacks the capabilities the step needs.

**Why this priority**: Optional power-user configuration; the default
claude-only setup fully works without it.

**Independent Test**: Provide a `KESTREL_BACKENDS_FILE` mapping `plan` to a
text-only LLM backend and `implement` to a file-editing backend, then observe
via `GET /api/backends` and workflow step detail that steps resolve to the
configured backends, and that mapping a text-only backend to `implement` is
rejected.

**Acceptance Scenarios**:

1. **Given** a backends TOML file, **When** kestrel starts, **Then** it builds
   one backend per entry, validates the default session backend on startup, and
   reports the effective config at `GET /api/backends`.
2. **Given** a step-to-backend map, **When** a step is dispatched, **Then** the
   step resolves to its mapped backend (dotted sub-steps fall back to the parent
   step, then to the default).
3. **Given** a step requiring `file_edits`, **When** it is mapped to a
   text-only backend, **Then** dispatch is refused because the backend's
   capabilities are not a superset of the step's requirement.

---

### Edge Cases

- **Unknown session on the event stream**: `GET /api/sessions/{id}/events` for
  an unknown id yields an empty stream (no subscriber is registered; no queue
  leak) rather than an error.
- **Resume/delete of an unknown session**: raises a not-found condition in the
  service layer; the sessions router does not map service exceptions to specific
  HTTP status codes, so they surface via default error handling.
- **Backend restarted mid-step**: on startup, workflow runs left in a transient
  status (`cloning`/`refining`/`planning`/`implementing`/`opening_pr`) are set
  to `failed` ("backend restarted mid-step"); runs at an `awaiting_*` gate are
  recovered with a fresh control future and re-enter at the gate.
- **Legacy persisted events**: rows written before the canonical schema (raw
  claude stream-json without `kind`/`native`) are remapped on read, falling back
  to `unknown`, so history survives upgrades.
- **Agent not logged in / turn error**: a terminal result flagged as an error
  (e.g. "Not logged in · Please run /login") surfaces as a backend turn error
  rather than a normal result.
- **Empty implement diff**: treated as a blocker requiring operator input, not
  as a completed change.
- **Refine interview runaway**: bounded by a soft round cap (3) that can grow
  per retry up to a hard cap (6); specialist generation failures are recorded
  as soft (retried) or hard (given up) generation issues.
- **Unauthenticated GitHub reads**: with no token, public issue/repo reads may
  succeed unauthenticated; write operations (issue PATCH, push, PR) require the
  token and fail loudly without it.
- **opencode write safety**: on read-only turns (refine/plan) file-mutating
  tools (`edit`/`write`/`patch`) are both disabled per-message and rejected at
  the permission prompt; other tools including `bash` are auto-approved (a
  documented prompt-injection risk in the alpha).

## Requirements *(mandatory)*

### Functional Requirements — Session dispatch & lifecycle

- **FR-001**: System MUST expose `POST /api/sessions` accepting `{prompt}` and
  returning `{session_id}` once the agent reports its id, spawning the agent in
  a fresh per-run workspace.
- **FR-002**: System MUST expose `POST /api/sessions/{id}/resume` accepting
  `{prompt}` that reuses the existing session's workspace and appends new events
  to the same record, setting status back to `running`.
- **FR-003**: System MUST expose `GET /api/sessions` returning a summary per
  session (`session_id`, `status`, `event_count`, `created_at`, and the
  `repo#issue` workflow that used the workspace if any).
- **FR-004**: System MUST expose `DELETE /api/sessions/{id}` that terminates any
  live subprocess and removes the session record and its events.
- **FR-005**: System MUST represent a session's status as at least `running`
  (active) and `idle` (terminal result observed); status flips to `idle` when a
  `result` event is appended.
- **FR-006**: The system MUST return from session start as soon as the id is
  known and continue consuming the agent's output stream in the background.

### Functional Requirements — Per-run workspaces

- **FR-007**: System MUST create each ad-hoc session's workspace at
  `{workspace_root}/session-{8 hex}` and each workflow run's workspace at
  `{workspace_root}/wf-{8 hex}`, created lazily.
- **FR-008**: Workspaces MUST remain on the host filesystem under
  `KESTREL_WORKSPACE_ROOT` (default `./.kestrel-workspaces`; `/workspaces` in
  the image) so their file edits are browsable and isolated per run.
- **FR-009**: Workflow workspaces MUST be populated by cloning the target repo
  and checking out the run's branch; ad-hoc session start creates only the
  directory (no `git init`/clone by kestrel itself).

### Functional Requirements — Canonical event stream (SSE)

- **FR-010**: System MUST normalize every backend's native stream onto one
  canonical event vocabulary: `assistant_text`, `user_text`, `tool_use`,
  `tool_result`, `thinking`, `system`, `rate_limit`, `result`, `error`,
  `unknown`.
- **FR-011**: System MUST stream session events over Server-Sent Events at
  `GET /api/sessions/{id}/events`, first replaying all recorded events in order
  and then delivering live events.
- **FR-012**: SSE responses MUST use anti-buffering headers
  (`Cache-Control: no-cache`, `X-Accel-Buffering: no`) and emit keepalive
  comment frames after at most ~15s of idle so proxies do not buffer and clients
  stay connected.
- **FR-013**: System MUST provide live SSE snapshots for workflows
  (`GET /api/workflows/{id}/events`) and notifications
  (`GET /api/notifications/events`); these buses deliver a "re-read" tick and
  the route re-serializes the authoritative store snapshot each time so ordering
  cannot drift.
- **FR-014**: Event ordering MUST be by insertion (persisted event autoincrement
  id / in-memory arrival order); there is no explicit per-event sequence number
  on the wire. Workflow steps carry an explicit `position`.

### Functional Requirements — Persistence

- **FR-015**: System MUST persist state in SQLite via SQLAlchemy, with schema
  owned by Alembic; application code MUST NOT `create_all` or emit raw DDL.
- **FR-016**: Each store operation MUST own its own transaction (a
  `sessionmaker.begin()` write or plain read session); there MUST be no
  request-scoped `get_db` dependency (deliberate contract deviation).
- **FR-017**: The in-memory registries MUST write through to the stores on every
  mutation and MUST preload persisted state on startup so sessions,
  workflows, and notifications survive restarts.
- **FR-018**: Timestamps MUST be stored as naive UTC (deliberate contract
  deviation acceptable while single-process/single-zone).
- **FR-019**: Deletes MUST preserve referential integrity by removing child rows
  before parents (events before session; notifications and steps before run).

### Functional Requirements — Pluggable backends & capability policy

- **FR-020**: System MUST address backends through one `Backend` protocol
  (`start` / `resume` / `run_turn` / `terminate`, plus an `id` and a capability
  set) so callers never depend on a specific tool's flags or output format.
- **FR-021**: System MUST define capabilities `text`, `file_edits`, `tool_use`
  and MUST serve a step with a backend only when the backend's capabilities are
  a superset of the step's requirement; a mismatch (e.g. a text-only LLM for an
  `implement` step) MUST be refused.
- **FR-022**: Step requirements MUST be: `refine`/`plan` require `text`;
  `implement` requires `text` + `file_edits`; unknown steps default to `text`.
- **FR-023**: System MUST be configurable from a backends TOML file
  (`KESTREL_BACKENDS_FILE`) defining the default session backend, a step→backend
  map, and per-backend connection settings; when absent, the system runs
  claude-only. Config is read once at startup and reported at
  `GET /api/backends`.
- **FR-024**: The bundled `claude_cli` backend MUST invoke the host's logged-in
  `claude` CLI as a subprocess with `--output-format stream-json`, deriving the
  permission mode and model from settings/policy, and MUST NOT use an
  `ANTHROPIC_API_KEY` or an Agent SDK.
- **FR-025**: The `opencode` backend MUST dispatch over HTTP to a separately-run
  `opencode serve` addressed by URL, scoping file tools to the session workspace
  and enforcing read-only turns on refine/plan.
- **FR-026**: The `openai_compat` backend MUST dispatch over HTTP to a
  self-hosted OpenAI-compatible endpoint addressed by URL, advertise `text` only,
  and reconstruct conversation history from persisted canonical events.
- **FR-027**: External backends (opencode, self-hosted LLMs) MUST be reached by
  URL and MUST NOT be bundled into the image; only the `claude` CLI is bundled.

### Functional Requirements — Issue→PR GitHub workflow

- **FR-028**: System MUST expose workflow endpoints under `/api/workflows`:
  create (`POST` with `{repo, issue_number}`), list, detail, SSE events, delete,
  and the human-in-the-loop controls `reply`, `approve`, `reject`,
  `answers/draft`, and `answers`.
- **FR-029**: A workflow MUST have the fixed ordered steps `refine`, `plan`,
  `implement`, a branch `kestrel/issue-{n}`, and its own workspace; and MUST
  progress clone → refine → plan → implement → deliver.
- **FR-030**: The workflow MUST pause at human approval gates
  (`awaiting_refine_approval`, `awaiting_plan_approval`,
  `awaiting_implement_approval`) and MUST only accept approve/reject while a gate
  is awaiting a decision; approve MAY carry an edited deliverable, reject MAY
  carry a refinement prompt to regenerate.
- **FR-031**: The refine stage MUST run a profile-aware, multi-round clarifying
  interview: a coordinator selects stakeholder profiles, per-profile generators
  produce structured questionnaires, questions are reconciled/deduplicated, and
  operator answers advance the interview until the coordinator returns none.
- **FR-032**: The refined issue MUST be written back to the GitHub issue on
  approval with a `<!-- kestrel:refined -->` sentinel appended, and a workflow
  created for an already-sentineled issue MUST skip refine.
- **FR-033**: The refined issue MUST include a deterministic
  "## Assumptions & accepted risks" section assembled in code from waived
  answers (never paraphrased by the model).
- **FR-034**: The implement stage MUST resume the plan session, run with an
  edit-permitting permission mode, and use the git diff as the deliverable; an
  empty diff MUST become an `awaiting_implement_input` blocker.
- **FR-035**: On implement approval the system MUST commit all changes, push the
  branch, and open a **draft** pull request whose body closes the issue, then
  store the PR URL and end the run `done`.
- **FR-036**: Deleting a workflow MUST drop all local work and MUST NOT modify
  anything on GitHub.

### Functional Requirements — Questionnaire mechanism

- **FR-037**: Questions MUST carry an id, prompt, rationale, a type
  (`single_select` / `multi_select` / `boolean` / `free_text`), required flag,
  options, audience, and dropped-source metadata.
- **FR-038**: Answers MUST accept a concrete value, a waiver
  (`{waived, reason}` with reason required), a custom correction, or a noted
  value; unknown ids and type mismatches MUST be rejected; drafts MAY be partial.
- **FR-039**: The interview envelope (questionnaire, draft answers, accumulated
  Q&A, round state) MUST be persisted so an in-progress interview survives
  restart.
- **FR-040**: A generation failure MUST be recorded as a soft issue (retried) or
  hard issue (given up) rather than silently dropping an audience.

### Functional Requirements — Git & GitHub integration

- **FR-041**: Git operations MUST run via the git CLI with the GitHub token
  injected per-command as an HTTP Basic auth header (never written to
  `.git/config`, redacted in errors), and commits MUST be made with a fixed
  kestrel identity and signing disabled.
- **FR-042**: GitHub operations (read issue, read default branch, PATCH issue,
  create PR) MUST use the GitHub REST API with a Bearer token when configured,
  and the only secret kestrel itself consumes MUST be the optional
  `KESTREL_GITHUB_TOKEN`.

### Functional Requirements — Notifications & health

- **FR-043**: System MUST record workflow notifications (per run/issue, with
  read state) and stream the current list over SSE, newest first.
- **FR-044**: System MUST expose health endpoints whose readiness check includes
  the database dependency (per `docs/observability.md`).

### Non-Functional / Constraint Requirements

- **NFR-001**: The system MUST remain single-user and unauthenticated (bound to
  loopback); multi-user auth is out of scope, the only planned protection being
  a shared-secret access gate.
- **NFR-002**: The system MUST run in two modes — a bundled Docker image
  (backend + built SPA + `claude` CLI) and a run-from-source developer flow —
  and migrations MUST run idempotently on container start.
- **NFR-003**: Agent authentication MUST be inherited from the host `claude`
  login (mounted read-only), never re-implemented by kestrel.
- **NFR-004**: Frontend business types in `frontend/src/types/` MUST mirror the
  backend JSON shapes (`SessionSummary`, `SessionEvent`, workflow, questionnaire,
  notification) and stay in sync with API changes.

### Key Entities

- **SessionRecord / `session` row**: one agent session — `session_id`, `cwd`
  (its workspace), `status`, `created_at`; owns an ordered list of events.
- **CanonicalEvent / `event` row**: one normalized timeline entry — `kind`
  (from the canonical vocabulary), `session_id`, and kind-specific fields
  (text, tool name/input/summary, is_error, tokens, subtype, model, tools,
  mcp_servers, duration, status, and the raw `native` payload).
- **WorkflowRun / `workflow_run` row**: one issue→PR run — `id` (`wf-…`),
  `repo`, `issue_number`, `issue_title`, `base_branch`, `branch`, `workspace`,
  `status`, `pr_url`, `error`; owns ordered steps.
- **WorkflowStep / `workflow_step` row**: one stage of a run — `position`,
  `name` (`refine`/`plan`/`implement`), `session_id`, `status`, `deliverable`,
  `model`, `refine_round`.
- **Backend**: a dispatch target with an `id` and a capability set, built from
  configuration (`claude_cli` / `opencode` / `openai_compat`).
- **Profile**: a stakeholder audience persona used to route the refine interview
  (prompt-routing only; carries no access control).
- **Questionnaire / Question**: the structured clarification presented during
  refine, plus its typed answers and the persisted interview envelope.
- **Notification / `notification` row**: a per-run/issue message with read
  state.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can dispatch a prompt and see the first live event in
  the browser within the agent's own start-up latency, with no manual refresh
  (SSE, live).
- **SC-002**: A dispatched session's full event history is recoverable after a
  backend restart — reopening its stream replays every recorded event in the
  original order.
- **SC-003**: An operator can drive a GitHub issue to an opened draft PR entirely
  through the API/UI, passing through each approval gate, with the resulting PR
  closing the referenced issue.
- **SC-004**: A step mapped to a backend that lacks the required capability is
  refused before any subprocess/HTTP dispatch (no partial work is performed).
- **SC-005**: An in-progress refine interview and any `awaiting_*` workflow gate
  survive a backend restart and can be resumed; transient in-flight steps fail
  loudly instead of resuming inconsistently.
- **SC-006**: No agent or GitHub credential is stored by kestrel beyond the
  optional `KESTREL_GITHUB_TOKEN`; agent auth is always the host `claude` login.

## Assumptions

- **Single operator, trusted network**: the API is unauthenticated and bound to
  loopback; concurrent multi-user access is out of scope for this baseline.
- **Host `claude` login present**: the bundled path assumes a logged-in `claude`
  CLI and its `~/.claude` credentials mounted into the container.
- **External backends run separately**: opencode and self-hosted LLMs are
  started outside kestrel and reachable by URL (and, for opencode, share the
  workspace mount).
- **Alembic migrations applied**: stores assume the schema is migrated
  (`alembic upgrade head`) before preload; the app does not create tables at
  runtime.
- **GitHub token scope**: the issue→PR feature assumes a token with Contents,
  Issues, and Pull-requests read/write (or classic `repo`); without it the
  feature is effectively disabled.
- **Single process / single timezone**: naive-UTC timestamps are accepted while
  everything runs in one process and zone.

## Known quirks captured for fidelity *(descriptive, not requirements)*

- The `error` canonical event kind exists in the vocabulary but is not currently
  produced by the claude mapper.
- The `claude_cli` backend advertises `text` + `file_edits` but not `tool_use`,
  even though the CLI uses tools; no step currently requires `tool_use`.
- The sessions router does not translate service-layer not-found/start errors
  into specific HTTP status codes.
- Several workflow control endpoints are declared `async` but invoke the service
  synchronously.
- "Profile" denotes an interview stakeholder persona, which is unrelated to
  backend selection despite the overlapping everyday meaning of the word.

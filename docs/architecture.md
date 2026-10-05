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
  `estimation`, `implementation`, `verification`, `reconciliation`, `coordinator_review`)
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

### Specialist dispatch, delivery, and write-back (spec 026, complete as of T078)

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

A result that cannot be read at all (malformed JSON, a missing block) is
not escalated straight away (feature 042, `retries.py`). The work runs
again as a fresh card of the same kind, which records the attempt it
replaces (`source_card_id`) and is told why that attempt could not be
used. This happens up to `board_unreadable_retry_cap` times (default 1).
After that the result is escalated, and the operator can **Retry** from
the escalation: the work runs again as a fresh card, and the escalation
closes. A replaced attempt does not count as an interview round or an
understanding draft.

An escalation records the card it escalates (`source_card_id`, feature
041). The display-only phase projection (`phases.py`) places it in that
card's phase, not in Build. An escalation with no source, and an
`analysis` card the coordinator starts before the PRD is signed off, is
placed in the earliest phase that has other open work, and never later
than its own kind's phase.

**Deliberately still out of scope**: kestrel never pushes a coder's
commits or opens a change request, for either an initial implementation
or a verified remediation. Nothing currently decides "verification
passed, therefore deliver" — a clean verification result (empty findings)
creates no follow-up card at all, so the loop has no explicit "done, ship
it" signal yet. This is now the most important remaining gap (tasks.md
T067-T069, which also covers the rest of task-source write-back below).

**As of 2026-09-26, three of the five milestone kinds actually post** (spec
026 T067, partial): `app/services/board/write_back.py::post_projection`
plans (via `projections.py`), posts via `TaskSource.post_comment()`, and
resolves exactly one projection, idempotent by key and never raising on a
post failure (recorded as retryable instead). Wired for **gate decisions**
(resolving a decision gate posts one plain sentence for its kind and
outcome, such as `"PRD signed off."`; an interview gate posts nothing),
**escalations** (a `coordinator_review` card — created either by a
verifier's routed finding, T051, or an operator's own "request
coordinator review" — posts `"Escalation: <summary/title>"`), and an
**approved task breakdown** (below) — see `tests/test_board_write_back.py`,
`tests/test_board_verification.py`, and
`bootstrap.py::schedule_gate_projection`/`schedule_escalation_projection`.

**As of 2026-09-27, task decomposition is built** (spec 026 T068): a `pm`
card of the dedicated `decomposition` kind (distinct from the shared
`analysis` kind other roles also use, so dispatch can route its result by
card kind rather than sniffing free-form text) proposes a candidate
breakdown as a `<DECOMPOSITION>{"tasks": [...]}</DECOMPOSITION>` block.
`app/services/board/decomposition.py::route_decomposition_result` parses
it, durably stores the raw candidate as a `HandoffArtifact` (via the new
`ArtifactsService.store_reference_artifact`, which persists content
without the card-acceptance side effects `submit_result` carries), and
opens a `decomposition_gate` human gate referencing it — an unparseable
result escalates to `coordinator_review` instead (fail closed, same
pattern as T051's verifier routing). What approving the gate does is
described under spec 031 below.

This intentionally does **not** resurrect the old fixed driver's
propose→self-critique→revise loop (`technical_analysis.py`, deleted in
Phase 10) — the human gate is the quality backstop instead; a rejected or
poorly-scoped candidate is retried like any other card.

**As of 2026-09-28, CAB-2 has something to decide on** (spec 030,
GitHub #50–#52). The `pm`'s `<DECOMPOSITION>` block now also classifies
every task as `coding` or `manual` and carries 1–2 paragraphs of summary
prose. It is validated strictly (`app/services/board/candidate.py`): an
unclassified task is rejected, never assumed agent-eligible. A valid
candidate no longer opens the gate directly. Instead
`route_decomposition_result` creates an `estimation` card for `developer`
(read-only workspace), with a dependency edge on the decomposition card
through which it reads the candidate. The coordinator cannot create
that card kind.

`developer` answers with `<ESTIMATES>`, giving per task: size S/M/L/XL,
confidence, man-hours by hand, agent tokens, review hours, risk flags and
a rationale. `app/services/board/estimation.py` validates the result
against the candidate: it must cover every task exactly once, and manual
tasks must cost no agent tokens or review time. On success it stores the
merged `cab2_proposal` (the gate target, and the structured record a
later estimate-vs-actual feature will read). It then opens the
`decomposition_gate` titled with the coding/manual split and stores an
executive summary on the gate card itself, so the summary is the gate's
`latest_artifact`. The summary's totals are computed by
`exec_summary.py`, not written by an agent, and it makes no go/no-go
recommendation. Invalid estimates fail closed to `coordinator_review`.

**As of 2026-09-29, approved tasks are cards in the request's own
workflow** (spec 031, GitHub #54). This reverses spec 012, which published
each approved task as a child ticket that was then ingested as a workflow of
its own, with its own branch and PR. Approving the `decomposition_gate`
now runs `app/services/board/materialise.py` inside `GatesService.resolve`:

- per coding task, an `implementation` card for `coder` and the
  `verification` card that checks it;
- per manual task, a `manual_task` card that no specialist can claim. The
  operator completes it from the cockpit (`complete_manual_task`).

Prerequisites become dependency edges between the tasks' head cards. Every
card carries its task in `board_card.task_node_id`, and each head card holds
the approved text and estimate as a `task_spec` artifact. That artifact is
what every card on the task works from (`_extra_context_for`). The
coordinator cannot change these cards. The request's ticket gets one
breakdown comment instead of one ticket per task. `TaskSource.create_subtask`
stays on the port, unused, for mirroring cards back as sub-tasks later
(backlog epic #63).

The result is **one request → one workflow → one branch → one PR** by
construction. A tagged verification with findings creates tagged
remediation plus a re-verification. After `max_verify_iterations` rounds it
escalates to `coordinator_review` instead (`verification_rounds.py`). A
clean verification requests delivery only once no coding, verification,
reconciliation or review work is open or failed, and every approved task's
work is verified (`delivery_readiness.py`). The request is keyed by the set
of finished implementation cards, so each set delivers once. Manual tasks
never hold back delivery, but they keep the request out of Done, and the
stage board counts them ("N manual tasks assigned to you").

**How a request ends (feature 040).** The board derives each request's
`outcome` from its cards (`phases.outcome_of`); nothing is stored:

- `failed`: any card failed. The request stays in the column where it
  failed, flagged. Only the operator retries or cancels a failed card; the
  coordinator may not.
- `in_progress`: anything is still open.
- `done`: it reached its end, meaning a done delivery, or CAB-2 approving
  only manual tasks and all of them done.
- `cancelled`: it stopped before its end with nothing failed (a gate
  rejected, work cancelled). It goes to the trailing Cancelled column.

Every card being terminal is not enough to count as done. The default
listing hides only done and cancelled requests.

**Accepted trade-off:** per-task tickets in GitHub/Jira are gone for now.
The task source was the only place people without kestrel access could
follow per-task progress. Mirroring cards back as sub-tasks is on the
backlog as #63 (#64). Resolving gates from a Jira ticket is built since
feature 046 (#65, see [Working with kestrel on the
ticket](#working-with-kestrel-on-the-ticket-feature-046)); manual tasks are
still resolved in the UI.

Decomposition is **enforced**, not just offered. It is mandatory, like
CAB-1 and PRD sign-off, since #70; the former
`board_decomposition_required`, `board_prd_gate_required` and
`board_cab1_gate_required` switches are gone. This reflects that Kestrel is sometimes only one part of a larger system where
an ingested task is high-level and may include non-development work, so
every workflow must pass an approved decomposition (CAB-2) before any
other work starts — even if the decomposition is a single task covering
everything. This is enforced two ways, deliberately redundant: `GatesService`
deterministically creates the `decomposition` card itself right after
`understanding_gate` is approved (so it isn't left to coordinator
discretion), and `CoordinatorService.apply_actions` independently rejects
any other card-creating action until a `decomposition_gate` card reaches
`done` — the first guarantees the assessment starts, the second guarantees
nothing else can happen in parallel with it. See `tests/test_board_decomposition.py`,
`tests/test_board_gates.py::TestDecompositionEnforcement`, and
`tests/test_board_coordinator.py::TestDecompositionEnforcement`.

**As of 2026-09-27, a clean verification delivers itself** (spec 026
T069): `route_verifier_result`'s result now also reports whether the
verifier's turn found nothing at all (`VerificationRouting.clean`) —
not even a remediation-worthy nonconformance. When it did, the
coordinator creates a `delivery` card the same way T051's remediation/
escalation cards are created (system-computed, not LLM-proposed, but
still routed through `CoordinatorService.apply_actions`). Every dispatch
pass then attempts any `ready` `delivery` card
(`dispatch_ready.py::_dispatch_pending_delivery`): it pushes the
workflow's worktree branch (`WorkspaceService.push`, new) and opens a
*draft* change request (`CodeHost.open_change_request` — unused since
the driver's deletion, needed no changes), then projects
`kind="delivery"` (T067's last real gap). Unlike `decomposition_gate`,
this is deliberately **not** human-gated: publishing kestrel's own
worktree branch as a draft PR is low-risk and reversible, so the
verification's own pass/fail is trusted as the gate.

A **temporary, dev-only** pair of actions also now exists for repeating
a local dry run without restarting kestrel or hand-editing the database
(`app/services/board/dev_reset.py`, `app/routers/board_dev.py`): cleanup
cancels a workflow's open cards, revokes active claims, and tears down
its workspace; rerun layers cleanup with a fresh `understanding_gate` on
the same workflow row. Gated behind `board_dev_actions_enabled` (off by
default — the routes don't exist unless it's on) and, regardless of the
flag, restricted to a `private`-visibility workflow, the same safety
property the old deleted `workflows/reset.py`'s own `rerun` enforced.
Meant to be deleted outright once the board is production-ready, not
hardened — see the module's own docstring before extending it. Abandon
only blocks *new* dispatch, not an already-running specialist turn:
nothing in the dispatch loop retains a cancellable handle for one (see
below), so an in-flight turn simply finishes and its result is discarded
against the now-cancelled card.

**As of 2026-09-27, a failing required CI check repairs itself too**
(spec 026 T052): three new `Workflow` fields (`change_request_number`,
`ci_repair_round`, `ci_status`) let `app/services/board/ci_poll.py::
CiPollService` — the board's **first periodic external-provider poll
loop** (`recovery.py`'s own sweep only watches the board's own claim-
lease store, nothing external) — check each delivered workflow's
`Settings.required_ci_statuses_for` checks via `CodeHost.
required_ci_statuses` (unused since the old driver's deletion until
now). A failure within `max_ci_repair_iterations` creates a `coder`-
eligible repair card, deliberately reusing `CardKind.IMPLEMENTATION` —
the same kind T051's verifier-triggered remediation already uses,
rather than a new card kind — and past that budget, one
`coordinator_review` escalation instead (fail closed, T051/T068's own
pattern), after which that workflow is never polled again. A repaired
workflow redelivers onto its *existing* change request rather than
opening a second one — `delivery.py::deliver` now checks `workflow.
change_request_number` first — since a plain `git push` fast-forwards
the same worktree branch and GitHub/GitLab already update an open PR/MR
on push. `ci_repair_round`/`ci_status` reset on every fresh delivery, so
an operator's own manual fix (a new delivery, same as an automated
repair) earns a fresh repair budget rather than staying permanently
excluded once escalated.

**As of 2026-09-30, delivery records where the change request is and
what it shows** (spec 043). `board_workflow.change_request_url` sits
beside the number and is exposed on the board snapshot, and the
cockpit's "Pull request" entry links to it. A redelivery onto the
existing change request keeps both values: its location is a note, not
a URL, and earlier it cleared the recorded number. When delivery opens
the change request, `delivery_body.py` composes the body. It lists the
PNGs the coder committed under `.kestrel/screenshots/` (or states the
reason in the `README.md` there) as images served by
`CodeHost.file_url` from the pushed branch. A redelivery leaves the body
as it is. The cockpit renders Markdown artifacts through `markdown-it`
with raw HTML disabled, so agent output never becomes live markup
(amended 029 FR-015).

**As of 2026-09-27, the refinement-interview and PRD-approval gates are
built** (spec 026 T078) — the last of the four human gates the data
model always had slots for (`understanding_gate`/`refinement_gate`/
`prd_gate`/`decomposition_gate`) but that, until now, only
`understanding_gate` (and, when enabled, `decomposition_gate`) ever
actually got created. Now mandatory (#70; originally gated behind a
`board_prd_gate_required` setting): approving `understanding_gate` deterministically
creates three parallel interview cards, one per business-altitude
persona (`requester`/`pm`/`uiux`, matching the old deleted driver's own
`BUSINESS_ALTITUDE_IDS` split) — each drafts its own scoped question set,
routed into a `refinement_gate` a human answers via a new free-text
field on the gate-resolution API. Once every interview reaches a
terminal state, `pm` drafts a PRD folding in every answer, routed into a
`prd_gate`; approval records `Workflow.approved_prd` and finally
projects `kind="approved_artifact"` — the last of the five FR-033
milestone kinds, closing that gap as a side effect of building this
rather than as its own task (see tasks.md's T067/T078 notes). Technical-
altitude personas (infosec/architect/dba/ops/qa) and cost-estimation
(since added by spec 030, above) were explicitly scoped out for this pass — decomposition still stands in
for that "technical analysis" step, per T068 — and may become their own
later iteration.

Building this surfaced a real foundational gap, fixed alongside it: no
card's envelope — not even the coordinator's own wake-up turn — ever
carried the task's actual content, only its short display title; the
quarantine-screened body was computed at intake and silently discarded.
`coder`'s own prompt already assumed a PRD-scoped "approved scope"
concept with no board-domain implementation behind it. Fixed via two new
`Workflow` fields, `task_body` (threaded from intake) and `approved_prd`,
both now included in every card's envelope
(`dispatch.py::build_card_envelope`/`build_coordinator_envelope`).

**As of 2026-09-28, a persona's interview can span more than one round,
and a `prd_gate` rejection is triaged instead of auto-redrafted**
(feature 028, GitHub #48/#49). Both are capped via new settings,
`board_refinement_round_cap`/`board_prd_redraft_cap` (both default `1`,
preserving the single-round/single-redraft behavior above exactly).
A persona's round number is derived by counting its own
`refinement`/`refinement_gate` cards, not stored — a round created by
the coordinator (below) is counted identically to one `gates.py` creates
directly. A specialist can also declare its interview done before the
cap via a `"satisfied": true` field on the existing
`<REFINEMENT_QUESTIONS>` tag; when paired with no further questions,
`GatesService.mark_refinement_satisfied` completes that persona's
`refinement` card directly, with no gate. A `prd_gate` rejection no
longer deterministically creates a fresh `prd` card
(`gates.py::_maybe_redraft_prd`, now in `prd_redraft.py`); instead, up to
the redraft cap, it asks the coordinator to judge — reusing the exact
bounded-retry-then-escalate shape `ci_poll.py`'s CI-repair loop already
used — via a `coordinator_review` card the coordinator's next (already
automatic) wake-up turn resolves into either a `prd` redraft or a fresh
interview round. Past the cap, that same escalation path creates a
final, never-auto-resolved `coordinator_review` card instead, so an
unconvergeable PRD fails visibly rather than looping. The coordinator's
own envelope (`build_coordinator_envelope`) now also carries this
rejection feedback, reusing `refinement.gather_refinement_context`
rather than a new mechanism.

**As of 2026-09-29, intake is visible and the understanding is real**
(spec 032, #67/#68). A picked-up ticket gets its request straight away,
titled only by its ticket ref and holding no content, with a "Screening
input" card that no specialist claims. Only then does the input-security
classification run (`services/board/intake.py`,
`IngestionService._screen`). Creating the request wakes nothing
(`BoardService.open_screening`).
- **Safe input:** the request gets its title and body, and a `pm`
  `understanding` card. That one commit wakes the coordinator.
- **Suspect input:** it is quarantined on the same request. A release
  completes the review card and continues the request (`continue_intake`).
  A discard cancels the card. Resolving a review that is no longer
  pending does nothing (feature 041). A restart mid-screening re-screens
  the request on the next poll.
- **The understanding step:** `pm` writes a restatement
  (`<UNDERSTANDING>`). Only a readable one opens the `understanding_gate`,
  which targets it, and the cockpit shows it inline. A rejection requires a
  correction and redrafts, up to `board_understanding_redraft_cap`; past
  the cap it opens a coordinator review (`understanding.py`,
  `understanding_redraft.py`).

Practically, this means a configured GitHub/Jira/local source today
creates a board **Workflow** on a qualifying task, screens it in place,
and starts the understanding step; specialist cards then progress
automatically, including a `coder` role committing real file edits to
its own local worktree branch, and human gates/interventions still
happen in the Kestrel web UI, or, for a Jira ticket, as a reply on the
ticket (feature 046). Gate decisions, escalations,
an approved task breakdown, an approved PRD, and a clean verification's
delivery all now get reported back to the ticket itself (T067/T069/T078,
spec 031); what an operator still can't see from the source or a PR
alone is anything short of those milestones — day-to-day card-by-card
progress is still Kestrel-UI-only.

## Working with kestrel on the ticket (feature 046)

For the alpha, a Jira ticket is where people work with kestrel. kestrel
says what people need to read on the ticket, and people answer there. The
kestrel UI stays available as a fallback, and interviews keep their own
forms, reached by a link. This section is the system context; the design
history is in [specs/046-jira-first-alpha](../specs/046-jira-first-alpha/).

### The document boundary

Anything kestrel reads from or writes to a platform is a **document**, never
a string in that platform's syntax (constitution, Principle VI).

- `app/documents.py` holds the closed set of constructs: paragraphs, text,
  links, mentions, lists, tables, markers and so on. It knows no format.
- `app/document_formats/` holds one module per platform format (Markdown,
  Atlassian Document Format, document JSON). Parsing into a document and
  rendering out of one happen only here.
- An import-linter contract (`documents-at-the-boundary` in
  `backend/.importlinter`) lets only the adapter at each system boundary
  import `document_formats`: task sources, code hosts, agent text,
  screening, the persistence column and the HTTP API. Every allowed edge
  is named. Services, routers and the board build and read documents and
  never see a format.

So an announcement is built from constructs, and the Jira adapter renders
it to ADF when it posts. Wording lives in
`app/services/board/announcements/`, one builder per announcement.

### The announcement flow

```
board change ─▶ AnnouncementService ─▶ projection ledger ─▶ adapter ─▶ ticket
 (gate opens,    (decides what has       (idempotency key,    (renders   (one comment,
  request ends)   not been said yet)      payload kept)        to ADF)    marked "posted")
```

- Opening a gate records a `gate.opened` event. The announcement service
  looks at the request after every board change and says, once, whatever it
  has not said yet: the restatement, the PRD, the interview pointer, the
  "ready for CAB" summaries, delivery, failure.
- Every announcement goes through the **projection ledger**. Its
  idempotency key (`gate_opened:{card}`, `gate_opened:batch:{plan}`,
  `delivery:{card}`, `reply:{comment}`, ...) makes each comment at-most-once
  across passes and restarts. The ledger keeps the document, so a failed
  post is retried later by the retry loop, never twice.
- A decided gate says one plain sentence for its kind and outcome (for
  example "PRD signed off."), from one mapping in
  `announcements/decisions.py`. Interview gates say nothing when resolved:
  the next announcement is the acknowledgement.
- Comments carry an ownership **marker** the adapter adds, so kestrel can
  tell its own comments from replies.
- The person to ask is mentioned: the reporter for the requester's gates,
  the change owner for the CAB gates and for "move this ticket on". CAB
  members are never mentioned; kestrel does not know who they are.

### The reply flow

```
poll ─▶ filter ─▶ claim ─▶ match gate ─▶ entitled? ─▶ screen ─▶ liaison ─▶ resolve
                                                       │ held ▶ operator ▶ release
```

`CommentPollService` reads the comments of active requests on Jira sources,
oldest first, from a stored position. `ReplyService` then handles each:

1. **Filter.** Only a comment carrying the reply marker (`@kestrel` by
   default, `feedback_marker`) counts, and never one of kestrel's own.
2. **Claim.** The comment's id is stored before anything else, so it is
   acted on at most once, across cycles, restarts and edits.
3. **Match.** The comment belongs to the gate that was open when it was
   written, so a late reply never decides the next gate. It only counts if
   it was written **after kestrel's announcement of that gate was posted**.
   An older comment, or any comment while the announcement is still
   unposted, is recorded as `ignored` and gets no answer.
4. **Entitlement.** The reporter decides the requester's gates, the change
   owner the CAB gates, both read fresh from the ticket and compared by
   account id. A stranger is told so, and nothing changes. Interview
   answers are never taken from the ticket; the reply gets a pointer to the
   form.
5. **Screening.** The text goes through the same input-security boundary as
   any task intake. A suspicious reply is **held** for the operator, and the
   ticket is told. Releasing it continues that one reply; discarding it
   tells the ticket it was not acted on.
6. **Liaison.** A specialist with no workspace and no tools reads what the
   reply means: approve, reject (with a reason), or unclear. Anything it
   cannot read cleanly, a timeout included, fails closed: kestrel asks the
   person to say it again, and decides nothing.
7. **Resolve.** A clear answer resolves the gate through
   `GatesService.resolve`, the same call the UI makes, credited to the
   person and the channel ("decided via Jira"). A rejection that needs a
   reason and has none is asked back.

Each considered reply gets one short answer on the ticket (except
`ignored`), mentioning its author. A decision taken on the ticket posts that
answer, which reuses the decision sentence, instead of the UI's line.

### The no-transition rule

kestrel never changes the status of a ticket it ingested (constitution,
access model, fourth constraint). It does not move, close or resolve it.
Where the ticket should move on, kestrel says so in a comment to the change
owner. Nothing in the announcement or reply code calls
`TaskSource.transition`, and a test over a whole request asserts it.

## Design trade-offs

- **Single-user, no auth.** Deliberate for the alpha: kestrel is a personal
  tool bound to loopback. Multi-user/authn is out of scope. One exception:
  the GitHub webhook endpoint (`POST /api/github/webhook`) is intended to
  face the network so GitHub can deliver events; its authenticity gate is an
  HMAC signature, not loopback binding (see the constitution's access model).
  The endpoint currently handles only the `issues` event (label-trigger
  ingestion) — the `issue_comment` /
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

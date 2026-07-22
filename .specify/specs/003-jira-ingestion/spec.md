# Feature Specification: Jira Ingestion & Autonomous Design/Code/Verify Loop

**Feature Branch**: `feat/003-jira-ingestion`

**Created**: 2026-07-21

**Status**: Draft

**Input**: User description: "Ingestion of Jira items for a semi-autonomous agentic coding loop. Work starts when a user creates a change request in the Jira RFC project — that is the trigger. Kestrel stays agnostic of company internals. Jira may not offer webhooks short-term, so polling is a needed fallback. The first step after the RFC is refinement; clarifications are posted back as Jira comments; when clarification is done the final PRD is attached to the Jira item and a notification is created for PRD approval/rejection. Implementation is conceptually three specialists — a designer (high-level architecture + implementation plan), a coder (implements the plan), and a verifier (checks the implementation against plan/design/request and can punt work back to the coder). Once work enters the designer, the design/code/verify loop runs 100% autonomously and results in a merge request in the code repository with a notification to Jira carrying the PR link. Take inspiration from plan-mode / spec-kit without losing autonomy."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Automatically start a run from a Jira RFC (Priority: P1)

A team member creates (or transitions) a change request in the Jira RFC project.
Kestrel notices the qualifying RFC on its own, determines which code repository the
RFC targets, and starts a workflow run for it — with no manual repo/issue entry in
the kestrel UI. The originating RFC and the code it will change live in **different**
systems (Jira vs. a git repository), so kestrel resolves the target repository from
the RFC itself before the run can begin.

**Why this priority**: This is the entry point of the whole milestone — moving the
trigger from "a maintainer clicks Start in kestrel" to "a change request in Jira sets
work in motion." Without RFC ingestion and target-repository resolution, none of the
downstream refinement or autonomous implementation can happen. It is also the first
place kestrel must operate against a task source (Jira) whose code lives in a separate
code host, which is the defining new capability of this feature.

**Independent Test**: Configure the RFC project, the qualifying filter, and the
repository-resolution field. Present a qualifying RFC (via a stubbed Jira API) whose
resolution field names a reachable repository, wait for one poll cycle, and confirm
exactly one run is created and targets the resolved repository, remote, and base
branch. Present the same RFC on a later cycle and confirm no second run is created.

**Acceptance Scenarios**:

1. **Given** a qualifying RFC in the watched RFC project whose repository-resolution
   field names a reachable repository, **When** the next poll cycle runs, **Then**
   kestrel starts exactly one workflow run for that RFC, targeting the resolved
   repository, remote, and base branch, and it appears in the existing workflow list.
2. **Given** an RFC that already produced a run, **When** later poll cycles observe it
   again (unchanged or updated), **Then** kestrel starts no additional run for it.
3. **Given** an RFC that does not match the qualifying filter (wrong project, status,
   or label), **When** a poll cycle observes it, **Then** kestrel starts no run.
4. **Given** a qualifying RFC whose repository-resolution field is empty or names a
   repository kestrel cannot resolve or reach, **When** a poll cycle observes it,
   **Then** kestrel starts no run, records the unresolved reason, and posts a comment
   on the RFC stating that the target repository could not be determined.
5. **Given** Jira is unreachable or rejects the poll query, **When** a poll cycle runs,
   **Then** kestrel logs the failure, starts no partial or erroneous runs, and retries
   on the following cycle.

---

### User Story 2 - Refine the RFC and gate PRD approval through Jira (Priority: P1)

After a run starts, kestrel refines the RFC into a Product Requirements Document (PRD).
When the refinement needs human clarification, kestrel posts a **thin** notification on
the Jira RFC — carrying only a deep-link to kestrel's existing refinement questionnaire,
not the questions or any refinement content — and waits. The human answers in that
questionnaire form using the existing questionnaire feature. Once clarification is
resolved, kestrel attaches the final PRD to the Jira RFC and posts an equally thin
notification (status + deep-link) asking a human to approve or reject it in the UI. Only
an approved PRD unlocks the autonomous implementation loop; a rejected PRD stops the run
(or returns it to refinement).

**Why this priority**: This is the single deliberate human checkpoint of the whole
loop — the point where a person confirms kestrel understood the request before it
autonomously writes and verifies code. The task source (Jira) is only the boundary that
tells the human "input is needed here"; the actual clarification and approval happen in
kestrel's own questionnaire/approval UI, keeping the posted notification thin and keeping
kestrel agnostic of company process. Without this gate, autonomy would run on an
unvalidated understanding of the request.

**Independent Test**: Drive a started run through refinement with a stubbed Jira API.
Force a clarification round and confirm a clarification comment is posted to the RFC
and the run holds. Resolve the clarification, and confirm the PRD is attached to the
RFC and an approval notification is raised with a deep-link. Approve it and confirm the
run proceeds to design; reject it and confirm the run does not proceed to design.

**Acceptance Scenarios**:

1. **Given** a run in refinement that needs clarification, **When** kestrel raises the
   clarification, **Then** a thin comment stating that input is needed — carrying only a
   deep-link to kestrel's existing refinement questionnaire, and no questions or content —
   is posted on the RFC, and the run holds until the human answers in that questionnaire.
2. **Given** refinement has completed, **When** the PRD is ready, **Then** kestrel
   attaches the PRD to the RFC and posts a thin comment (status + deep-link only)
   announcing that PRD approval or rejection is required in the UI.
3. **Given** a PRD awaiting approval, **When** a human approves it, **Then** the run
   proceeds into the design step.
4. **Given** a PRD awaiting approval, **When** a human rejects it, **Then** the run does
   not proceed into design, and its outcome (rejected or returned to refinement) is
   recorded and reflected on the RFC.
5. **Given** posting a clarification, PRD attachment, or approval comment to Jira fails,
   **When** the failure occurs, **Then** the run still reaches and holds its gate, the
   gate is still visible in the in-app notification center, and the failure is logged.

---

### User Story 3 - Run design → code → verify autonomously to a merge request (Priority: P1)

Once a PRD is approved, the run enters the design → code → verify loop and runs it with
**no human approval gates**. A designer produces the high-level architecture and
implementation plan; a coder implements it on the run's isolated working copy; a
verifier judges the implementation and either accepts it or punts it back to the coder
with feedback. The verifier bases its judgment on the **observed behaviour of the running,
modified project** wherever possible: it runs the project in the isolated working copy and
exercises its boundary — issuing real HTTP requests against an HTTP API (e.g. a FastAPI
service), or driving and visually inspecting the UI via browser automation (Playwright) for
a web GUI (e.g. a Vite app) — and grounds the verdict in what the project actually does,
not model opinion alone. Where behavioural exercise is unavailable it falls back to the
project's own checks and then to judging against the design, PRD, and original request. The
code→verify cycle repeats until the verifier accepts or a bounded iteration limit is
reached. On acceptance, kestrel opens a merge request in the target code repository and posts a
comment on the Jira RFC carrying the merge-request link. On exhaustion of the iteration
limit, kestrel stops the loop and escalates to Jira for human attention instead of
looping forever.

**Why this priority**: This is the core value and the stated non-negotiable goal — a
100% autonomous design/code/verify loop that ends in a reviewable merge request. It is
the reason the feature exists; US1 and US2 exist to feed it a validated PRD and a target
repository.

**Independent Test**: Starting from an approved PRD (stubbed Jira + stubbed agent
backends), run the loop and confirm no human gate is entered during design, code, or
verify. Force the verifier to reject once and confirm the coder runs again and the
verifier re-checks. Force acceptance and confirm a merge request is opened and its link
is posted to the RFC. Separately, force the verifier to reject up to the iteration limit
and confirm the loop stops and an escalation comment is posted to the RFC instead of the
loop continuing.

**Acceptance Scenarios**:

1. **Given** an approved PRD, **When** the run enters design, **Then** design, code, and
   verify execute without pausing at any human approval or input gate.
2. **Given** the coder has produced an implementation, **When** the verifier runs the
   modified project and exercises its boundary (HTTP requests for an API, browser
   automation for a GUI) and judges the observed behaviour consistent with the PRD, **Then**
   the loop accepts and proceeds to open a merge request.
6. **Given** the project's observed behaviour does not satisfy the PRD (a failing HTTP
   assertion or UI interaction, or a failing configured check), **When** the verifier runs,
   **Then** it rejects and the failing observations are included in the feedback returned to
   the coder.
3. **Given** the verifier judges the implementation inconsistent, **When** iterations
   remain under the configured limit, **Then** the coder runs again with the verifier's
   feedback and the verifier re-checks the new result.
4. **Given** the verifier keeps rejecting, **When** the configured iteration limit is
   reached, **Then** the loop stops, no merge request is opened, and kestrel posts an
   escalation comment on the RFC asking for human attention.
5. **Given** the verifier accepts, **When** the merge request is opened in the target
   repository, **Then** kestrel posts a comment on the RFC containing the merge-request
   link.

---

### User Story 4 - One unified workflow across every task source (Priority: P2)

The reshaped workflow — refine → PRD approval → design → code → verify → merge request,
with the design/code/verify loop autonomous — is a **kestrel-internal** process that is
identical regardless of where the work came from. A task source (Jira RFC, GitHub issue,
or a manual start) is only the boundary at which the human and the agent meet: it is how
kestrel is triggered, where it posts thin attention notifications, and where it reports the
resulting merge/pull request. Behind that boundary the process behaves the same for every
source, so the system is predictable. To make this possible the run's origin is modeled as
two distinct concerns — a **task source** (read the ticket, comment on it, attach to it,
deep-link to it) and a **code host** (provision an isolated working copy, push, open a
merge/pull request). GitHub is one system implementing both roles; Jira implements the
task-source role and delegates the code-host role to the resolved repository; a manual
start uses the UI itself as its boundary. Adopting the unified workflow **changes** how
GitHub-sourced runs behave (they gain the PRD gate, the verify step, and the autonomous
loop) — deliberately, so that GitHub and Jira runs are indistinguishable in process.

**Why this priority**: A single predictable workflow is a core goal: the human should not
have to reason about "the Jira process" vs. "the GitHub process." The task-source/code-host
split is the structural change that makes both one process and lets a third source (GitLab,
Planka) join later without rework. It is P2 because US1–US3 carry the feature's value; this
story is what makes that value consistent across every entry point.

**Independent Test**: Start a run from a Jira RFC and a run from a GitHub issue (both
stubbed) and confirm they traverse the identical sequence of phases and gates, differing
only in which task-source/code-host implementations are bound and which surface receives
the thin notifications. Confirm a manual start traverses the same phases with the UI as its
boundary.

**Acceptance Scenarios**:

1. **Given** a Jira RFC, a GitHub issue, and a manual start, **When** each begins a run,
   **Then** all three traverse the same phase-and-gate sequence (refine → PRD approval →
   autonomous design → code → verify → merge request) via the same run lifecycle and
   storage.
2. **Given** the unified workflow, **When** a run originates from GitHub, **Then** its
   human touchpoints (clarification, PRD approval) surface as thin comments on the GitHub
   issue and its result surfaces as a pull request — the same shape as the Jira path, just
   on GitHub's surface.
3. **Given** any task source, **When** a run reaches a boundary event (attention needed,
   or merge/pull request opened), **Then** the notification content and behavior are the
   same across sources, differing only in the surface they are delivered to.

---

### User Story 5 - Stay reliable across restarts and be ready for webhooks (Priority: P3)

Because polling is the only transport initially, ingestion must be trustworthy without
webhooks: a qualifying RFC must eventually produce exactly one run even across restarts,
Jira outages, and overlapping poll cycles. The ingestion path is also structured so that,
if the Jira instance later gains webhook support, an inbound webhook can be added as an
additional trigger feeding the same ingestion logic — without reworking how runs start.

**Why this priority**: Polling alone is best-effort and single-user operation includes
restarts and flaky connectivity; idempotency and recovery make ingestion dependable. The
webhook-ready seam is a cheap structural precaution, not a shipped endpoint, so it is P3 —
valuable insurance that does not block the core loop.

**Independent Test**: Cause a qualifying RFC to be observed twice across a simulated
restart and overlapping cycles, and confirm exactly one run results. Confirm that the
ingestion decision (start / skip / unresolved) is exercised through a single source-neutral
entry point that a future webhook could call, and that processed-RFC tracking survives a
restart.

**Acceptance Scenarios**:

1. **Given** a qualifying RFC observed on two overlapping poll cycles, **When** both are
   processed, **Then** exactly one run is started.
2. **Given** kestrel restarts while an RFC has an in-flight or completed run, **When** the
   next poll cycle observes that RFC, **Then** no duplicate run is started.
3. **Given** the ingestion decision path, **When** a run is triggered, **Then** it flows
   through a single source-neutral entry point (the same one a future Jira webhook would
   call), with the poll cycle as one caller of it.

---

### Edge Cases

- **Repository not resolvable**: An RFC whose resolution field is empty, malformed, or
  names a repository kestrel cannot reach starts no run; the reason is logged and a
  comment on the RFC states the target repository could not be determined (so the human
  can fix the field), rather than failing silently.
- **Resolution field renamed/absent in Jira**: If the configured resolution field does
  not exist on the RFC schema, ingestion treats every RFC as unresolvable and surfaces a
  clear operator-facing error (misconfiguration), rather than starting mis-targeted runs.
- **RFC updated after its run started**: Edits to an already-ingested RFC do not start a
  second run and do not disturb the in-flight run or its merge request.
- **PRD rejected then RFC re-qualified**: A rejected run records a durable dismissal for
  its RFC; polling does not silently re-create a run for a dismissed RFC while it still
  qualifies. Re-triggering is an explicit gesture (mirroring the GitHub label
  remove/re-add "run it again" semantics), defined during planning for Jira's filter.
- **Verifier oscillation**: The verifier alternately accepts and rejects near the
  boundary; the iteration limit still bounds the loop and forces escalation rather than an
  endless cycle.
- **Autonomous step failure (non-verify)**: If design or code fails for a reason other
  than verifier rejection (agent error, push rejected), the run fails cleanly, escalates
  to Jira, and leaves no half-open merge request.
- **Merge request opened but Jira comment fails**: If the merge request is opened but
  posting its link to Jira fails, the merge request is not rolled back; the failure is
  logged and the in-app notification carries the link, so the work is never lost.
- **Jira comment/attachment retention & size**: Attaching a large PRD or posting many
  clarification rounds must not fail the run; oversize handling and comment cadence are
  bounded (planning detail), never model-generated free-form dumps of internal content.
- **Clarification never answered**: An RFC whose clarification gate is never answered
  holds indefinitely without consuming resources or repeatedly re-posting; a single
  comment per genuine gate entry (mirroring the GitHub gate-comment discipline).
- **Poll query returns many RFCs at once**: A backlog of qualifying RFCs on first run
  starts each at most once and does not overwhelm the system (bounded concurrency is a
  planning detail).

## Clarifications

### Session 2026-07-21

- Q: How does an RFC map to a code repository? → A: Kestrel reads a **configurable Jira
  field** on the RFC to resolve the target repository (and its remote/base branch). The
  field to read is operator-configured; a missing/unresolvable value blocks the run and
  is surfaced on the RFC (US1 AC-4).
- Q: How does the new autonomous loop relate to the existing refine → plan → implement
  workflow? → A: **Reshape** the existing workflow into refine → (PRD approval) →
  design → code → verify, and make it **unified across every task source**. The
  design/code/verify phases run gateless for **all** runs; GitHub and manual runs adopt the
  same phases and gates as Jira (they no longer hold at the old design/implement approval
  gates). The task source is only the human↔agent boundary, never a difference in process.
- Q: What bounds the verifier's ability to punt work back to the coder? → A: A
  **configurable maximum number of code↔verify iterations**. On exhaustion the loop stops
  and **escalates to Jira** (a comment on the RFC) rather than looping forever or shipping
  unverified work.
- Q: What transport detects new/updated RFCs in this feature? → A: **Polling now, with a
  webhook-ready seam.** Only polling ships; ingestion is structured so a future Jira
  webhook can feed the same source-neutral ingestion entry point. No off-loopback endpoint
  is added, so no constitutional access-model exception is introduced by this feature.
- Q: How are clarification answers and PRD approval collected — in Jira or in kestrel? →
  A: Requests go out as **Jira comments carrying a deep-link**; the human provides the
  answer / approval decision via the linked kestrel form (reusing the existing
  input/approval gate machinery). Ingesting free-text Jira comment replies or Jira status
  transitions as the answer/decision is a deferred enhancement, not in this feature.
- Q: Is the code host that a Jira RFC resolves to necessarily GitHub? → A: No. The code host
  is **operator-configured and self-hostable** (a self-hosted GitLab or Gitea/Forgejo, or
  GitHub), reflecting kestrel's sovereignty positioning (self-hostable, no mandatory external
  cloud). This feature ships GitHub plus one self-hosted git host as first-class; the port is
  drawn so further hosts are additional implementations only (FR-023a).
- Q: Should the verifier's verdict be based on model judgment alone, or on measurable
  outcomes? → A: On **measurable outcomes wherever possible** — the verify phase runs the
  operator-configured project checks (tests/type-check/lint/build) in the isolated working
  copy and grounds the verdict in those results, falling back to judgment only when no checks
  are configured. The verify interface carries this **evidence** explicitly so that deepening
  the grounding (the area expected to see the most future iteration) does not reshape the
  workflow (FR-015a).
- Q: What does "run the project and measure its behaviour" concretely mean for the verifier?
  → A: The design **assumes** the verifier **runs the modified project and exercises its real
  boundary** — real HTTP requests against HTTP APIs (FastAPI-style), and browser automation/
  visual inspection via Playwright for web GUIs (Vite apps). These two boundaries are the
  initial scope; other boundaries fall back to configured checks / model judgment. The exact
  behavioural-harness implementation is **not part of this change** (it may be delivered
  incrementally), but the analysis and design assume this model so later delivery does not
  reshape the workflow (FR-015b).

## Requirements *(mandatory)*

### Functional Requirements

#### Jira ingestion & polling (P1)

- **FR-001**: System MUST periodically poll the configured Jira RFC project for RFCs that
  match a configured qualifying filter (e.g. project + status and/or label) and treat a
  newly qualifying RFC as a trigger to start a run.
- **FR-002**: System MUST make the poll interval and the qualifying filter configurable.
- **FR-003**: System MUST continue operating when a poll cycle fails (Jira unreachable,
  rate-limited, or unauthorized), logging the failure and retrying on the next cycle
  without starting partial or erroneous runs.
- **FR-004**: System MUST authenticate to Jira using operator-supplied credentials sourced
  from configuration as secrets (never committed), and MUST never write those credentials
  to logs or error messages.
- **FR-005**: System MUST remain agnostic of company-internal Jira conventions: project
  key(s), status/label filter, and field names are configuration, not hard-coded values.

#### Ticket → repository resolution (P1)

- **FR-006**: System MUST resolve the target code repository for an RFC by reading a
  **configurable field** on the RFC, yielding the repository plus the remote and base
  branch needed to provision an isolated working copy.
- **FR-007**: System MUST NOT start a run for an RFC whose resolution field is empty,
  malformed, or names a repository it cannot resolve or reach; instead it MUST record the
  unresolved reason and post a comment on the RFC stating the target repository could not
  be determined.
- **FR-008**: System MUST treat a missing configured resolution field on the Jira schema as
  an operator misconfiguration surfaced clearly in logs, not as a reason to start
  mis-targeted runs.

#### Refinement & PRD approval via Jira (P1)

- **FR-009**: System MUST refine an ingested RFC into a PRD before any implementation
  begins.
- **FR-010**: When refinement requires human clarification, the system MUST post a comment
  on the originating RFC indicating input is needed (with a deep-link when a public UI base
  URL is configured) and MUST hold the run until the input is provided.
- **FR-011**: When refinement completes, the system MUST attach the final PRD to the
  originating RFC and MUST post a comment announcing that PRD approval or rejection is
  required (with a deep-link).
- **FR-012**: The system MUST NOT enter the design step until the PRD is approved, and MUST
  NOT proceed to autonomous implementation on a rejected PRD. A rejected PRD **ends the run in
  the `rejected` state and records a durable dismissal** for its ticket (it does not silently
  return to refinement); re-running is the explicit re-trigger gesture (FR-033). *(Decision:
  stop-and-dismiss over auto-return — auto-return could loop indefinitely on a genuinely
  ambiguous RFC; the human re-triggers when ready.)*
- **FR-013**: PRD approval and clarification answers MUST be collected through the existing
  kestrel input/approval gate (reached via the deep-link). Ingesting Jira comment replies
  or Jira status transitions as the decision is explicitly out of scope for this feature.

#### Autonomous design → code → verify loop (P1)

- **FR-014**: After PRD approval, the system MUST run the design, code, and verify phases
  without any human approval or input gate — for **every** run regardless of task source
  (the loop is autonomous and identical across sources).
- **FR-015**: The design phase MUST produce a high-level architecture and implementation
  plan; the code phase MUST implement that plan on the run's isolated working copy; the
  verify phase MUST judge the implementation against the design, the plan, and the original
  RFC/PRD.
- **FR-015a**: The verify phase MUST ground its judgment in the **observed behaviour of the
  running, modified project** wherever possible: the design assumes the verifier runs the
  project in the run's isolated working copy and exercises its boundary — issuing real HTTP
  requests for an HTTP-API project, or driving/visually inspecting the UI via browser
  automation for a web-GUI project — and makes those observations the primary basis of the
  verdict. The verify-phase interface MUST carry this behavioural evidence explicitly so that
  deepening it does not reshape the workflow, and the observations MUST be included in the
  feedback returned to the coder on rejection. Where behavioural exercise is unavailable, the
  verifier MAY fall back to operator-configured project checks (test/type-check/lint/build),
  then to model judgment over the diff and PRD.
- **FR-015b**: The initial supported project boundaries for behavioural verification are
  **HTTP APIs** (e.g. FastAPI services, exercised via HTTP requests) and **web GUIs** (e.g.
  Vite-built JS apps, exercised via browser automation such as Playwright). Other project
  boundaries are edge cases, out of the initial scope, and fall back per FR-015a. The exact
  behavioural-harness implementation (launching the project, scripting requests/interactions,
  browser automation, boundary detection) MAY be delivered incrementally and is NOT required
  in full by this feature — but the analysis and design MUST assume this behavioural model so
  later delivery does not reshape the workflow.
- **FR-016**: When the verifier judges the implementation inconsistent, the system MUST
  return work to the coder with the verifier's feedback and re-verify the new result,
  repeating until the verifier accepts or the iteration limit is reached.
- **FR-017**: The system MUST make the maximum number of code↔verify iterations
  configurable.
- **FR-018**: When the iteration limit is reached without acceptance, the system MUST stop
  the loop, open no merge request, and escalate by posting a comment on the RFC requesting
  human attention.
- **FR-019**: When the verifier accepts, the system MUST open a merge request in the target
  code repository and MUST post a comment on the originating RFC containing the
  merge-request link.
- **FR-020**: A failure in design or code for a reason other than verifier rejection MUST
  fail the run cleanly, escalate to Jira, and leave no half-open merge request.
- **FR-021**: The autonomous loop MUST reuse per-run isolated working copies so that
  concurrent runs cannot collide (consistent with the existing per-run isolation).

#### Unified workflow & Task Source / Code Host abstraction (P2)

- **FR-022**: The system MUST model a run's origin as two distinct concerns: a **task
  source** (read the ticket, comment on it, attach to it, build a deep-link to it) and a
  **code host** (provision an isolated working copy, push, open a merge/pull request).
- **FR-023**: GitHub MUST implement both the task-source and code-host roles for a single
  repository; Jira MUST implement the task-source role and delegate the code-host role to
  the repository resolved per FR-006; a manual start MUST use the kestrel UI itself as its
  boundary (no external ticket surface).
- **FR-023a**: The code host used for a Jira-resolved repository MUST be operator-configured
  and MUST support a **self-hosted** git host (e.g. a self-hosted GitLab or Gitea/Forgejo
  instance), not only a third-party cloud — consistent with kestrel's sovereignty posture
  (self-hostable, no mandatory external cloud dependency). "Merge request" and "pull request"
  are the same concept realized on the configured host. Adding a further host type MUST be an
  additional code-host implementation, not a change to the workflow.
- **FR-024**: **Every** run, regardless of task source, MUST traverse the same workflow
  phases and gates (refine → PRD approval → autonomous design → code → verify → merge/pull
  request) via the same run lifecycle, storage, and UI surfacing — differing only in the
  bound task-source/code-host implementations and the surface that receives boundary
  notifications. There MUST be no source-conditional gating.
- **FR-025**: The design → code → verify process MUST be an internal, source-agnostic
  kestrel capability that also applies when the task source is the existing GitHub issue
  path. Adopting the unified workflow MUST change GitHub-sourced runs to include the PRD
  gate, the verify phase, and the autonomous loop, so that GitHub and Jira runs are
  indistinguishable in process. What MUST be preserved for GitHub is its **boundary**
  behavior — triggering from a labeled issue (webhook + reconciliation), surfacing
  attention as issue comments, and opening a pull request — and the manual "Start workflow"
  trigger MUST continue to work, now feeding the same unified workflow.
- **FR-026**: The run's source (manual / github-issue / jira-issue) MUST remain an internal
  attribute used for attribution, boundary/notification routing, and ingestion logic, and
  MUST NOT be added to the API schema or frontend type (consistent with the existing source
  discriminator). It MUST NOT influence which phases or gates a run traverses (FR-024).

#### Notifications & deep-links (cross-cutting)

- **FR-027**: All outbound Jira notifications (clarification, PRD approval, escalation,
  merge-request link) MUST be posted as comments through the existing outbound-notification
  port, composed alongside the always-recorded in-app notification.
- **FR-028**: Jira comment posting MUST be best-effort and non-blocking: a failure to post
  MUST NOT fail, stall, or alter the run, and MUST be recorded in structured logs; the
  in-app notification is the fallback channel. There is no retry queue or catch-up sweep.
- **FR-029**: Jira comment bodies MUST be rendered from fixed, deterministic templates
  (never model-generated) and MUST contain only status, the relevant link (deep-link or
  merge-request link), and identifying references — never the PRD text, design, plan, or
  clarification content, which stays behind the kestrel UI. (The PRD itself is delivered as
  a Jira **attachment** per FR-011, not inlined in a comment.)
- **FR-030**: Deep-links MUST be stable across restarts — keyed by the durable run
  identifier — so a link posted before a restart still resolves the same run and gate
  afterward, and the kestrel UI MUST support opening a run and its active gate directly from
  such a link.

#### Idempotency, resilience & webhook-ready seam (P3)

- **FR-031**: System MUST start at most one workflow run per RFC, regardless of how many
  poll observations occur for it.
- **FR-032**: Processed-RFC / run-attribution state MUST survive restarts so that a restart
  neither loses a missed run nor double-starts an existing one.
- **FR-033**: Rejecting a PRD (or abandoning a run) MUST record a durable dismissal for its
  RFC so polling does not silently re-create a run for a dismissed RFC while it still
  qualifies. The **re-trigger gesture** for Jira is the RFC leaving and re-entering the
  qualifying filter: while a dismissed RFC still matches the filter it stays suppressed, but
  when it no longer matches, the poll MUST **clear its dismissal**, so re-qualifying the RFC
  starts a fresh run (mirroring the GitHub label remove/re-add gesture).
- **FR-034**: The ingestion decision (start / skip / unresolved) MUST be reached through a
  single source-neutral entry point, with the poll cycle as one caller, so a future Jira
  webhook can be added as an additional caller without reworking run start.
- **FR-035**: System MUST record, in structured logs, each RFC observation's outcome
  (started, skipped-duplicate, skipped-filtered, unresolved-repo, dismissed, failed) so the
  operator can diagnose why a run did or did not start.

#### Configuration, persistence & operability

- **FR-036**: All new configuration (Jira base URL, credentials, RFC project/filter,
  resolution field name, poll interval, max verify iterations, and the reused public UI base
  URL) MUST be sourced from configuration with secrets never committed, and the polling loop
  MUST only run when Jira ingestion is configured.
- **FR-037**: Any schema change required for Jira attribution, target-repository resolution,
  or dismissal MUST be introduced through a database migration (the schema is owned
  exclusively by migrations; no schema creation in application code). (Verify-iteration state
  is deliberately in-memory and requires no schema — see the design.)
- **FR-038**: New behavior MUST ship with automated backend tests that mock the Jira API and
  the agent backends and never run against a production database or a real coding-agent
  subprocess.

### Key Entities *(include if data involved)*

- **Jira RFC (Task Source ticket)**: A change request in the watched RFC project that, when
  it matches the qualifying filter, triggers a run. Carries its key/identifier, the
  resolution field naming its target repository, and the comment/attachment surface used for
  clarification, PRD delivery, approval, escalation, and the merge-request link.
- **Repository Resolution**: The mapping from an RFC to a concrete code repository plus its
  remote and base branch, read from a configurable RFC field. Blocks the run when
  unresolvable.
- **PRD (Product Requirements Document)**: The refined, human-approvable artifact produced
  from the RFC. Attached to the RFC; its approval is the one human gate before autonomy. Its
  content stays behind the UI and is never inlined into Jira comments.
- **Task Source (port)**: The origin ticket concern — read the ticket, comment on it, attach
  to it, build a deep-link. Implemented by GitHub (issue) and Jira (RFC). Internal; not
  surfaced to API/UI.
- **Code Host (port)**: The code-repository concern — provision an isolated working copy,
  push, open a merge/pull request. Operator-configured and **self-hostable**: implemented by
  GitHub (for GitHub-sourced/manual runs) and by a self-hosted git host (a GitLab/Gitea/
  Forgejo instance) for Jira-resolved repositories, per the sovereignty posture (FR-023a).
- **Verification Evidence**: The observed outcomes the verifier weighs — primarily the
  **behaviour of the running, modified project** exercised at its boundary (HTTP request/
  response observations for an API; browser-driven interactions and visual inspection for a
  GUI), and, as a fallback, the pass/fail of operator-configured project checks. Carried
  explicitly into the verify phase and the coder feedback (FR-015a); grounds the verdict in
  what the project actually does rather than model opinion. The exact behavioural harness is
  assumed by the design but MAY be delivered incrementally (FR-015b) and MUST NOT require
  reshaping the workflow.
- **Unified Workflow**: The single, source-agnostic phase-and-gate sequence every run
  traverses — refine → PRD approval → autonomous design → code → verify → merge/pull
  request. The one human gate is PRD approval; design/code/verify are gateless. There is no
  per-source gating: the task source changes only the boundary surface, never which phases
  or gates run.
- **Verifier Decision & Iteration Bound**: The verifier's accept/reject-with-feedback
  outcome per round, and the configurable maximum number of code↔verify rounds after which
  the loop escalates instead of continuing.
- **Merge Request Reference**: The link to the merge/pull request opened in the target code
  repository on verifier acceptance, posted back to the RFC.
- **RFC Dismissal (tombstone)**: A durable record that an RFC's run was rejected or
  abandoned, suppressing silent re-ingestion while the RFC still qualifies; cleared by the
  planned re-trigger gesture.
- **Workflow Run** *(existing, reshaped)*: The run pipeline, reshaped from refine → plan →
  implement into refine → (PRD approval) → design → code → verify. Gains a verify phase and
  becomes uniform across sources; GitHub and manual runs adopt the same phases and gates as
  Jira runs (they no longer hold at design/code/implement approval gates), keeping only
  their boundary behavior.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A team member can cause a run to start by creating/qualifying an RFC in Jira,
  with no interaction with the kestrel UI, in 100% of qualifying cases with a resolvable
  target repository while the service is online and reachable.
- **SC-002**: No qualifying RFC ever produces more than one run, across any mix of poll
  cycles, overlapping observations, and restarts (zero duplicate runs).
- **SC-003**: An RFC whose target repository cannot be resolved produces no run and results
  in an operator-visible reason both in logs and as a comment on the RFC, in 100% of such
  cases.
- **SC-004**: For any run with an approved PRD — regardless of task source — the design →
  code → verify loop completes without entering any human approval or input gate, in 100% of
  runs.
- **SC-005**: When the verifier accepts, a merge request is opened in the target repository
  and its link appears as a comment on the RFC, in 100% of accepted runs.
- **SC-006**: The code↔verify loop never exceeds the configured iteration limit; on
  exhaustion an escalation comment appears on the RFC and no merge request is opened, in
  100% of exhausted runs.
- **SC-006a**: When verification evidence is available (behavioural exercise of the running
  project, or configured checks), a failing observation never yields an accept verdict (the
  run does not open a merge request on failing evidence), and the failing observations appear
  in the feedback the coder receives, in 100% of such runs.
- **SC-007**: A run started from any task source (Jira, GitHub, or manual) traverses the
  identical workflow phases and gates; comparing a GitHub-sourced run and a Jira-sourced run
  shows the same process, differing only in the boundary surface. GitHub still triggers from
  a labeled issue and produces a pull request, and the manual start still works — all now
  feeding the one unified workflow.
- **SC-008**: A human interacting only through Jira (reading comments, opening the linked
  form, approving/rejecting the PRD) can carry a run from RFC to an opened merge request,
  without ever needing to first navigate kestrel by hand.
- **SC-009**: Jira credentials and the token/secret never appear in any log line or error
  message.
- **SC-010**: Failure to post any Jira comment never blocks or fails a run: the run still
  reaches its gate/outcome, the event is still visible in the in-app notification center,
  and the failure is visible in logs.
- **SC-011**: No Jira comment ever contains PRD, design, plan, or clarification content —
  only status, a link, and identifying references — across every notification type.

## Assumptions

- **Poll-only transport, webhook-ready** (confirmed): This feature ships polling only.
  Because no inbound endpoint is exposed, this feature introduces **no** new deviation from
  the constitution's loopback-bound, unauthenticated access model — unlike the GitHub
  webhook. If a Jira webhook is added later it becomes a second off-loopback endpoint
  requiring a constitution amendment at that time; the ingestion seam is shaped so that
  addition is cheap (FR-034).
- **Configurable repository-resolution field** (confirmed): The RFC names its target
  repository via an operator-configured field; kestrel does not infer the repository from
  company-internal conventions. Multi-repository RFCs (one RFC spanning several repos) are
  out of scope — one RFC resolves to one target repository.
- **One RFC → one run**: An RFC maps to at most one run for its lifetime; updates to an
  already-ingested RFC do not start additional runs and do not disturb an existing run or its
  merge request.
- **Reshape into one unified workflow, not fork** (confirmed): The existing workflow is
  reshaped into refine → (PRD approval) → design → code → verify and made **identical across
  every task source**, rather than maintaining separate per-source workflows. This
  deliberately changes GitHub-sourced runs (they gain the PRD gate, verify phase, and
  autonomous loop). The design/code/verify process is a kestrel-internal, source-agnostic
  capability that also runs against the existing GitHub task source. "Designer/coder/verifier"
  are conceptual specialist agents realized as steps with specialized system prompts,
  consistent with kestrel's existing per-agent system-prompt mechanism.
- **Human decisions via the linked UI, thin notifications** (confirmed): Clarification
  answers and PRD approval are provided through the existing kestrel questionnaire/approval
  gate, reached via a deep-link. The notification posted to the task source is **thin** — a
  status and deep-link only, never the questions, PRD, or any content. Interpreting free-text
  task-source comment replies or ticket status transitions as the answer/decision is a
  deferred enhancement.
- **PRD delivered as an attachment**: The PRD is attached to the RFC; Jira comments carry
  only status and links, never the PRD/design/plan text (consistent with the existing
  gate-comment discipline that keeps internal content behind the UI regardless of ticket
  visibility).
- **Task Source / Code Host extraction is now justified** (Constitution IV): The abstraction
  deferred by the GitHub feature ("seam now, extract with the second source") is extracted
  here because two concrete sources finally exist; it is not speculative generalisation. The
  `CodeHost` port likewise now has **two** concrete implementations (GitHub + a self-hosted
  git host), which is what justifies it rather than a single-host abstraction.
- **Self-hostable, sovereign by design** (confirmed): kestrel is meant to run inside an
  organisation that values independence, sovereignty, and information security — self-hosted,
  with pluggable models/agents and a self-hostable code host, and no mandatory external cloud
  service. The Jira-resolved code host defaults to and first-classes a self-hosted git host
  (GitLab/Gitea/Forgejo); GitHub.com is one option, not the assumption (FR-023a). This
  positioning also motivates evidence-grounded verification (below): a sovereign deployment
  may run a weaker on-prem model whose unaided judgment is trusted less, so the verdict is
  anchored to executable checks.
- **Behavioural, evidence-grounded verification** (confirmed): The design **assumes** the
  verifier runs the modified project and exercises its real boundary — real HTTP requests for
  HTTP-API projects (e.g. FastAPI), browser automation/visual inspection (Playwright) for web
  GUIs (e.g. Vite apps) — and grounds its verdict in the observed behaviour (FR-015a, FR-015b).
  HTTP APIs and web GUIs are the initial supported boundaries; other boundaries fall back to
  configured checks / model judgment. The **exact behavioural harness** (project launch, request/
  interaction scripting, browser automation, boundary detection) is **not required in full by
  this feature** and may be delivered incrementally; this feature ships the evidence-carrying
  interface (so later delivery does not reshape the workflow) and a minimal interim evidence
  gatherer. This grounding matters more under sovereignty, where a weaker on-prem model's
  unaided judgment is trusted less.
- **Agent backends unchanged**: Design, code, and verify are dispatched through the existing
  agent-backend mechanism (the host's logged-in coding-agent CLI / configured backends);
  this feature adds a verify step and specialized prompts, not a new backend model or an API
  key.
- **Bounded stores**: Processed-RFC / dismissal records are retained and bounded; exact
  retention/pruning is a planning detail, consistent with the existing delivery-record bounding.
  (Verify-iteration state is in-memory per run, not a persisted store.)

## Dependencies

- Existing `WorkflowRun` lifecycle, storage/registry, restart recovery, and UI surfacing —
  reshaped here into one unified, source-agnostic workflow (adding a verify phase and the
  autonomous loop) that every task source — Jira, GitHub, and manual — traverses identically.
- Existing outbound-notification port (the `Notifier` protocol and its composite) and the
  in-app notification channel — extended with a Jira comment implementation.
- Existing per-run isolated working-copy provisioning and cleanup (git worktree isolation) —
  reused for Jira runs against the resolved target repository.
- Existing per-agent system-prompt / specialist-profile mechanism and per-step backend/model
  routing — reused to realize the designer, coder, and verifier.
- Existing ingestion choke point and reconciliation-loop pattern — generalized to a
  source-neutral ingestion entry point with a Jira poll cycle as a caller.
- The constitution (`.specify/memory/constitution.md`) — Alembic-owned schema, store-owned
  session lifecycle, naive-UTC timestamps, test-first discipline, secrets never committed,
  and the backend-only source discriminator all constrain this feature. No new off-loopback
  access-model exception is introduced (poll-only).

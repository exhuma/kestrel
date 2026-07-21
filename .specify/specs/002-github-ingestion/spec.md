# Feature Specification: GitHub Ingestion & Repo Ops

**Feature Branch**: `feat/002-github-ingestion`

**Created**: 2026-07-21

**Status**: Draft

**Input**: User description: "M-C · GitHub ingestion & repo ops — Turn kestrel from 'click a button to start a run' into 'notices new/updated issues on its own.' Webhook ingress with HMAC signature verification + delivery dedup. Poll reconciliation as a safety net for missed/failed webhook deliveries. Per-run `git worktree` isolation instead of one shared clone (a `GitHubSource` task source)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Automatically start a run when an issue is flagged (Priority: P1)

The maintainer applies a designated label (e.g. `kestrel`) to a GitHub issue in a
watched repository. Kestrel receives the event, confirms it is authentic, and
starts a workflow run for that issue on its own — no manual repo/issue entry in
the UI. The maintainer watches the run appear and progress exactly as if they had
clicked "Start workflow".

**Why this priority**: This is the core value of the milestone — moving from
"click a button to start a run" to "notices flagged issues on its own." A single
maintainer can label an issue from anywhere (phone, GitHub UI) and kestrel picks
it up. Without it, nothing else in this feature matters.

**Independent Test**: Configure a watched repo and its shared secret, send a
signed `labeled` webhook payload for the designated label, and confirm a run is
created for that issue and becomes visible in the existing workflow list. Send
the same delivery twice and confirm only one run is created.

**Acceptance Scenarios**:

1. **Given** a watched repository and a correctly configured shared secret,
   **When** an issue in that repository is labeled with the designated label and
   GitHub delivers a correctly signed webhook, **Then** kestrel starts exactly one
   workflow run for that repo and issue number and it appears in the workflow list.
2. **Given** a webhook delivery whose signature does not match the shared secret,
   **When** it arrives at the ingress endpoint, **Then** kestrel rejects it, starts
   no run, and records the rejection without exposing the secret.
3. **Given** a webhook delivery kestrel has already processed (same delivery
   identifier), **When** GitHub re-delivers it (retry), **Then** kestrel
   acknowledges it but starts no additional run.
4. **Given** an issue event for a label other than the designated one, or for a
   repository that is not being watched, **When** it is delivered and verified,
   **Then** kestrel acknowledges it and starts no run.
5. **Given** an issue that already has an active or completed run, **When** a new
   qualifying event arrives for that same issue, **Then** kestrel does not start a
   duplicate run for it.

---

### User Story 2 - Catch up on deliveries that were missed (Priority: P2)

Kestrel was offline, or a webhook delivery failed, while an issue was labeled.
When kestrel is running, it periodically reconciles the watched repositories
against GitHub, discovers qualifying issues it never received an event for, and
starts the runs that should have been started — so a missed delivery only delays
a run, never loses it.

**Why this priority**: Webhooks are best-effort; deliveries are dropped during
downtime, network failures, or misconfiguration. Reconciliation makes ingestion
trustworthy without the maintainer having to notice and re-trigger by hand. It is
P2 because P1 delivers value on its own for the common (online) case.

**Independent Test**: With the webhook path disabled or unreachable, label a
qualifying issue directly on GitHub, wait for one reconciliation cycle, and
confirm kestrel starts the run. Confirm a second cycle does not start a second run
for the same issue.

**Acceptance Scenarios**:

1. **Given** a qualifying labeled issue for which no webhook was ever processed,
   **When** the next reconciliation cycle runs, **Then** kestrel starts exactly one
   run for that issue.
2. **Given** an issue that a webhook already produced a run for, **When**
   reconciliation runs, **Then** kestrel starts no additional run for it.
3. **Given** GitHub is unreachable or rate-limits the reconciliation query,
   **When** a cycle runs, **Then** kestrel logs the failure, starts no partial or
   erroneous runs, and retries on the following cycle.

---

### User Story 3 - Isolate each run so concurrent work cannot collide (Priority: P3)

Because ingestion can start runs without the maintainer pacing them, two runs for
the same repository can be in flight at once. Each run operates on its own
isolated working copy so that one run's branch, checkout, and file changes never
interfere with another's, and cleaning up one run never disturbs another.

**Why this priority**: Automatic ingestion makes concurrent same-repo runs a
normal occurrence rather than an edge case, so isolation becomes a correctness
requirement. It is P3 because P1/P2 deliver value first; isolation hardens the
system against the concurrency they introduce.

**Independent Test**: Trigger two runs for the same repository at nearly the same
time and confirm both complete with independent branches and working copies, with
neither run's files or git state visible to the other, and that finishing or
abandoning one run leaves the other's working copy intact.

**Acceptance Scenarios**:

1. **Given** two runs are started for the same repository, **When** both execute
   concurrently, **Then** each has a separate working copy and branch, and neither
   sees the other's uncommitted changes.
2. **Given** a run finishes or is abandoned, **When** its working copy is cleaned
   up, **Then** other in-flight runs for the same repository are unaffected.
3. **Given** a run operates on its isolated working copy, **When** it commits,
   pushes, and opens its draft pull request, **Then** the result is identical to
   the current single-clone behavior from the maintainer's perspective.

---

### Edge Cases

- **Malformed or unsigned payload**: A request missing the signature header, with a
  malformed body, or for an event type kestrel does not handle is acknowledged (to
  stop GitHub retrying) without starting a run, and does not error the service.
- **Secret rotation**: When the shared secret is changed, deliveries signed with the
  old secret are rejected as unauthentic; the maintainer must update both GitHub and
  kestrel.
- **Label removed then re-added**: Re-adding the designated label to an issue that
  already produced a run (still tracked) does not start a second run. If the issue
  was **dismissed** (its run abandoned), removing the label clears the dismissal and
  re-adding it starts a fresh run — this is the deliberate "run it again" gesture.
- **Abandoned run, label still present**: Abandoning a run records a durable
  dismissal for its (repo, issue); reconciliation and later webhook events skip that
  issue and do not silently re-create the run while the label remains.
- **Reconciliation vs. webhook race**: A webhook and a reconciliation cycle both
  observe the same qualifying issue at nearly the same time; only one run is started.
- **Watched repo the token cannot read**: If the configured token lacks access to a
  watched repository, reconciliation and issue lookup fail loudly in logs and start
  no run, rather than silently doing nothing.
- **Delivery-record growth**: The store of processed delivery identifiers does not
  grow without bound over the service's lifetime.
- **Run start failure after acceptance**: If a delivery is verified and deduped but
  the run cannot be started (e.g. issue no longer exists), the failure is recorded
  (outcome `run-failed`) and no run record and no dismissal are left behind, so the
  next reconciliation cycle re-attempts the still-labelled issue. The webhook does
  not retry the same delivery; reconciliation is the retry path.

## Clarifications

### Session 2026-07-21

- Q: On restart while a run holds at a gate (FR-022 recovery re-enters the
  `awaiting_*` state), should the gate comment be re-posted? → A: No — record
  durably the last gate a run was commented for; recovery into the same gate
  posts nothing. One comment per *genuine* gate entry.
- Q: If posting a gate comment fails (GitHub unreachable/error), how does the
  maintainer still learn of the gate? → A: The always-recorded in-app
  notification is the safety net. One best-effort GitHub attempt; on failure,
  log and rely on the in-app notification. No retry queue or catch-up sweep.
- Q: Gate comments land on a possibly-public issue — what may the body contain?
  → A: Generic status + link only. Reuse the fixed, deterministic per-status
  templates; never include refined description, plan, or questionnaire content.
  The deep-link carries the maintainer to the private UI for the actual content.
- Q: If a maintainer abandons an ingested run while the issue still carries the
  trigger label, should reconciliation re-create it? → A: No — abandon records a
  durable dismissal (tombstone) per (repo, issue); ingestion and reconciliation
  skip a dismissed issue until the trigger label is removed and re-added (removing
  the label clears the dismissal).
- Q: A delivery is deduped before the run is created, so how is a failed run-start
  retried? → A: Reconciliation retries. A failed start records the delivery outcome
  as `run-failed` and leaves no run record and no dismissal; the next reconciliation
  cycle finds the still-labelled issue with no run and re-attempts it. No
  webhook-level retry and no dedicated retry queue.
- Q: Should a run's `source` (ingested vs manual) be surfaced to the API/UI? → A:
  No — keep it internal (persisted for attribution and ingestion logic). It is not
  added to the API schema or frontend type; ingested and manual runs stay visually
  indistinguishable (FR-009).

## Requirements *(mandatory)*

### Functional Requirements

#### Webhook ingress & authenticity (P1)

- **FR-001**: System MUST expose an HTTP endpoint that accepts GitHub issue-event
  webhook deliveries.
- **FR-002**: System MUST verify each delivery's HMAC signature against a configured
  shared secret and reject any delivery whose signature is missing or does not
  match, starting no run for it.
- **FR-003**: System MUST verify the signature using a constant-time comparison so
  that verification does not leak information about the secret.
- **FR-004**: System MUST record the identifier of each processed delivery and MUST
  NOT act on a delivery whose identifier it has already processed (delivery dedup).
- **FR-005**: System MUST respond to authentic deliveries promptly enough that GitHub
  does not treat them as failed, performing run creation without blocking the
  acknowledgement on the run completing.
- **FR-006**: System MUST never write the shared secret, signatures, or the
  configured token to logs or error messages.

#### Triggering runs from issues (P1)

- **FR-007**: System MUST start a workflow run only for issue events that carry the
  designated trigger label AND originate from a watched repository.
- **FR-008**: System MUST start at most one workflow run per (repository, issue),
  regardless of how many qualifying events or reconciliation observations occur for
  it.
- **FR-008a**: Abandoning an ingested run MUST record a durable **dismissal** for
  its (repository, issue). While a dismissal is in effect, ingestion and
  reconciliation MUST NOT start a new run for that issue even if it still carries
  the trigger label. Removing the trigger label MUST clear the dismissal, so that
  re-adding the label starts a fresh run. The dismissal MUST survive restart.
- **FR-009**: System MUST create ingested runs through the same run lifecycle,
  storage, and UI surfacing as manually started runs, so an ingested run is
  indistinguishable from a manual one once created.
- **FR-010**: System MUST preserve the existing manual "Start workflow" trigger;
  ingestion is additive and MUST NOT remove or change the manual path's behavior.
- **FR-011**: System MUST acknowledge (without starting a run) qualifying-looking
  events that are for non-watched repositories, non-designated labels, or
  unsupported event types.

#### Poll reconciliation (P2)

- **FR-012**: System MUST periodically reconcile each watched repository against
  GitHub to find qualifying issues for which no run exists, and start the missing
  runs.
- **FR-013**: Reconciliation MUST be idempotent with the webhook path: an issue
  already handled by a webhook MUST NOT produce a second run via reconciliation, and
  vice versa.
- **FR-013a**: A failed run-start MUST leave no run record and no dismissal for its
  (repository, issue), so that reconciliation re-attempts the still-labelled issue on
  a later cycle. The failure MUST be recorded (outcome `run-failed`); retry is via
  reconciliation, not webhook redelivery or a dedicated retry queue.
- **FR-014**: System MUST continue operating when a reconciliation cycle fails
  (GitHub unreachable, rate-limited, or unauthorized), logging the failure and
  retrying on the next cycle without starting partial or erroneous runs.
- **FR-015**: System MUST make the reconciliation interval configurable and MUST
  allow reconciliation to function while the inbound webhook path is unavailable.

#### Per-run isolation (P3)

- **FR-016**: System MUST give each run its own isolated working copy of the
  repository so that concurrent runs for the same repository do not share
  checked-out files, branches, or index state.
- **FR-017**: Cleaning up or abandoning one run MUST NOT disturb the working copy or
  git state of any other in-flight run.
- **FR-018**: A run operating on its isolated working copy MUST produce the same
  externally observable outcome (branch pushed, draft pull request opened, PR URL
  surfaced) as the current single-clone behavior.
- **FR-019**: Run dispatch MUST be organized so that the source of a run (an ingested
  GitHub issue vs. a manual request) is a distinct, identifiable concern, allowing
  future task sources without reworking run execution.

#### Gate notifications & deep-links (P1)

Because ingestion starts runs without the maintainer at the UI, a run that
reaches a human-input gate can block unnoticed. The originating GitHub issue is
the one place the maintainer is guaranteed to see, so gate events are announced
there with a link back to the exact form.

- **FR-023**: When a run enters any state that requires the maintainer's
  attention (any `awaiting_*` gate — both "needs your input" questionnaires and
  "ready for review/approval" gates), the system MUST post a comment on the run's
  originating GitHub issue describing what is needed.
- **FR-024**: Each gate comment MUST include a stable link that opens directly on
  that run's relevant view/form in the kestrel UI when a public UI base URL is
  configured. When no public UI base URL is configured, the comment MUST still be
  posted, without a link.
- **FR-025**: The system MUST post a new comment for each distinct gate entry
  (e.g. each refinement round re-entering an input gate), rather than editing a
  prior comment, so each attention event is independently visible and linkable.
- **FR-026**: Gate-comment posting MUST be best-effort and non-blocking: a
  failure to post (GitHub unreachable, comment rejected) MUST NOT fail, stall, or
  alter the run, and MUST be recorded in structured logs. A single best-effort
  attempt is made per gate entry; the always-recorded in-app notification (which
  is raised for every gate transition independently of the comment) is the
  fallback channel. There is no retry queue or catch-up sweep for failed
  comments.
- **FR-027**: Gate links MUST be stable across restarts — keyed by the durable
  run identifier — so a link posted before a restart still resolves the same run
  and gate afterward.
- **FR-028**: The kestrel web UI MUST support opening a specific run, and its
  currently-active gate form, directly from such a link (deep-linking), without
  the maintainer first navigating to that run by hand.
- **FR-029**: Gate comments and links MUST NOT contain the shared secret, the
  GitHub token, or signatures (reaffirming FR-006 for this new output surface).
- **FR-030**: Gate comments MUST be idempotent across restarts: the system MUST
  durably record the last gate a run was commented for, so that restart recovery
  re-entering the same `awaiting_*` state (per FR-022) posts no comment. A comment
  is posted only on a genuine new gate entry, not on recovery of an unchanged
  gate.
- **FR-031**: Gate comment bodies MUST be rendered from fixed, deterministic
  per-status templates (never model-generated) and MUST contain only the gate
  status and the deep-link — never the refined description, plan, or
  questionnaire content, which stays behind the UI. This holds regardless of the
  issue's visibility (the issue may be public).

#### Configuration & operability

- **FR-020**: System MUST source the shared secret, watched repositories, trigger
  label, and reconciliation interval from configuration, with the shared secret
  provided as a secret (never committed).
- **FR-020a**: System MUST source the public UI base URL used to build gate
  deep-links from configuration; it MAY be unset, in which case gate comments are
  posted without a link (see FR-024).
- **FR-021**: System MUST record, in structured logs, each delivery's outcome
  (accepted, rejected-signature, duplicate, ignored, run-started, run-failed) in a
  way that lets the maintainer diagnose why a run did or did not start.
- **FR-022**: System MUST recover cleanly across restarts: processed-delivery records
  and any pending ingestion state survive a restart so a restart neither loses a
  missed run nor double-starts a completed one.

### Key Entities *(include if data involved)*

- **Webhook Delivery Record**: A durable record that a specific GitHub delivery
  (identified by its delivery id) has been processed, with its outcome and time.
  Exists to guarantee at-most-once action per delivery and to bound retention.
- **Watched Repository**: A configured repository (`owner/name`) that kestrel is
  allowed to ingest from and reconcile against. Ingestion and reconciliation ignore
  anything outside this set.
- **Trigger Configuration**: The designated label that flags an issue for ingestion,
  plus the reconciliation interval. Determines which issues qualify.
- **Task Source**: The identifiable origin of a run — an ingested GitHub issue vs. a
  manual request. A GitHub issue source carries the repo and issue number; the
  concept exists so runs can be attributed and so future sources can be added. It is
  an **internal** attribute (persisted, used by ingestion logic) and is NOT surfaced
  to the API or UI, so an ingested run stays indistinguishable from a manual one
  (FR-009).
- **Run Working Copy (Isolated)**: The per-run isolated checkout a run operates in,
  owned by exactly one run and cleaned up with that run, independent of other runs.
- **Issue Dismissal (tombstone)**: A durable record, keyed by (repository, issue),
  that the maintainer abandoned that issue's run. Suppresses re-ingestion and
  reconciliation for the issue while the trigger label remains; cleared when the
  label is removed, so re-adding it starts fresh. Bounds "zombie re-runs" of an
  intentionally abandoned issue.
- **Gate Notification**: An attention event raised when a run enters an
  `awaiting_*` gate, delivered both in-app (existing) and as a comment on the
  run's GitHub issue (new). Carries the run's repo/issue, the gate status, and a
  deep-link to the run's form. One comment is posted per gate entry.
- **Gate Deep-Link**: A stable URL, built from the configured public UI base URL
  and the durable run id, that opens the kestrel UI on that run and its active
  gate form. Resolves the same run/gate across restarts; absent when no public UI
  base URL is configured.
- **Workflow Run** *(existing)*: The repo/issue-scoped pipeline (refine → plan →
  implement → open PR). Unchanged in lifecycle; this feature adds new ways to create
  one and changes how its working copy is provisioned.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A maintainer can cause a run to start by labeling an issue on GitHub,
  with no interaction with the kestrel UI, in 100% of qualifying cases while the
  service is online and reachable.
- **SC-002**: A qualifying issue labeled while kestrel was offline or during a failed
  delivery still results in exactly one run, no later than one reconciliation
  interval after the service is back and reachable.
- **SC-003**: No qualifying labeled issue ever produces more than one run, across any
  mix of webhook retries, offline/online transitions, and reconciliation cycles
  (zero duplicate runs).
- **SC-004**: 100% of deliveries with an invalid or missing signature are rejected
  and start no run.
- **SC-005**: Two runs started for the same repository within the same minute both
  complete without either observing or corrupting the other's files or git state.
- **SC-006**: The maintainer can determine, from logs alone, why any given labeled
  issue did or did not start a run (accepted, rejected, duplicate, ignored, or
  failed).
- **SC-007**: The secret and token never appear in any log line or error message.
- **SC-008**: The store of processed-delivery records stays bounded over continuous
  operation (does not grow unbounded).
- **SC-009**: When a run reaches a human-input gate, a comment appears on its
  GitHub issue announcing what is needed; when a public UI base URL is configured,
  that comment's link opens the maintainer directly on the run's gate form, in
  100% of gate entries — with no prior UI navigation.
- **SC-010**: Failure to post a gate comment never blocks or fails the run: the
  run still reaches and holds its gate, the gate is still visible in the in-app
  notification center, and the failure is visible in logs.
- **SC-011**: No gate comment ever contains refined-description, plan, or
  questionnaire content (only the gate status and deep-link), across every gate
  type and issue visibility.

## Assumptions

- **Watched-repo allow-list**: Kestrel watches a maintainer-configured allow-list of
  `owner/name` repositories. Events and reconciliation outside that list are ignored.
  (Not asked; a bounded allow-list is the safe single-user default and matches how
  GitHub webhooks are configured per repo.)
- **Trigger is a label** (confirmed): A designated label (default name chosen during
  planning, e.g. `kestrel`) applied to an issue flags it for ingestion. Applying the
  label to a new or existing issue both qualify.
- **One run per issue**: An issue maps to at most one run for its lifetime; updates
  to an already-ingested issue do not start additional runs and do not disturb an
  existing run or its PR. Re-running an issue remains a manual action, unchanged by
  this feature.
- **Transport** (confirmed): Inbound webhook delivery plus poll reconciliation as a
  fallback. The webhook endpoint must be reachable by GitHub, which is a deliberate,
  recorded deviation from the constitution's loopback-bound API; the HMAC signature
  is the authenticity gate for that endpoint. How the endpoint is exposed (tunnel,
  reverse proxy) is the operator's responsibility and out of scope here. This
  deviation MUST be reconciled with the constitution during `/speckit-plan`.
- **Auth model unchanged**: Ingestion reuses the existing single GitHub token for
  reading issues and reconciling; no GitHub App / installation-token model is
  introduced by this feature.
- **Existing pipeline reused**: Ingestion and reconciliation only *start* runs; the
  refine → plan → implement → draft-PR pipeline, its human approval gates, and its
  restart-recovery behavior are unchanged.
- **Issue-listing capability**: Reconciliation requires querying issues by label from
  GitHub; this read capability does not exist yet and is assumed to be added as part
  of this feature (a behavioral requirement, not an implementation directive).
- **Delivery retention**: Processed-delivery records are retained long enough to cover
  GitHub's retry window and are then bounded/pruned; an exact retention policy is a
  planning detail.
- **Public UI exposure**: Gate deep-links require the kestrel UI to be reachable at
  a configured public base URL. How that URL is exposed (tunnel, reverse proxy) is
  the operator's responsibility and out of scope here — the same operator-exposure
  posture already recorded for the webhook endpoint. When unconfigured, gate
  comments are still posted, without a link. This shares the webhook's deliberate
  deviation from the constitution's loopback-bound API and MUST be reconciled with
  the constitution during `/speckit-plan`.
- **Gate comments apply to any issue-backed run**: A gate comment is posted for any
  run that has an originating GitHub issue, regardless of whether the run was
  ingested or started manually — consistent with FR-009 (ingested and manual runs
  are indistinguishable once created). Scoping comments to ingested-only runs is a
  possible refinement, deferred unless it proves noisy in practice.
- **Multi-source is a future direction; this feature is GitHub-only** (decided): More
  ingestion sources (Jira soon, then GitLab, Planka, …) are planned, but building a
  source-abstraction framework now would be speculative generalisation against a
  single concrete implementation (Constitution IV). The decision is *seam now,
  extract with the second source*: this feature ships GitHub only, keeping its
  boundaries port-shaped (the `Notifier` protocol is the outbound port; the
  `ingestion` service + the `source` discriminator are the inbound seam), and the
  real domain interfaces are extracted during the Jira feature when two concrete
  implementations exist. The load-bearing seam is **Task Source vs Code Host**: a run
  needs a *ticket* (read/notify/deep-link) and a *code repository* (clone/worktree/
  push/PR); GitHub collapses both into one system (hence `WorkflowRun.repo` +
  `issue_number` and PRs on the same client), but Jira is a task source whose code
  lives in a *separate* repo, requiring a ticket→repo resolution. That resolution and
  the `TaskSource`/`CodeHost` interfaces are **out of scope here** and owned by the
  Jira feature; this feature MUST avoid adding GitHub coupling beyond what GitHub
  itself needs, so the later extraction stays cheap.

## Dependencies

- Existing `WorkflowRun` lifecycle and its storage/registry, restart recovery, and
  UI surfacing (the run created by ingestion is the same one manual entry creates).
- Existing GitHub token configuration and repository access.
- Existing per-run workspace provisioning and cleanup, which this feature changes
  from a full clone to an isolated per-run working copy.

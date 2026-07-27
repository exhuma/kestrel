# Feature Specification: Task-Source Lifecycle Sync, Time Tracking, and Operator Hooks

**Feature Branch**: `006-task-lifecycle-sync`

**Created**: 2026-07-27

**Status**: Draft

**Input**: User description: "Kestrel needs a way to interact more with the task sources. We need a way to transition the state of a task into an 'in progress' and 'done' state as well as updating a 'spent time' metric representing the true wall-clock time that was spend implementing the task. The challenge here is that every task-source implements this differently. Some platforms may or may not offer certain of these fields. If they are not supported, kestrel should add a footer to the comments it made with these stats. What complicates this even more is that some platforms like Jira are highly configurable and kestrel cannot predict what actions (apart from the standard Jira ones) must be taken during those life-cycle events. This makes me think that we need some form of 'hook' concept. An easy win might be to provide a 'hooks' folder to kestrel which contain executable and communicate via stdin/stdout (taking inspiration from git hooks). We should also measure the 'wait-time' (how long work was waiting on human input). A failure should not flag the task as 'done'. We can provide a failure hook as well. Authentication must also be considered: hook subprocesses inherit kestrel's own environment (and thus its credentials) by design."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ticket reflects run status automatically (Priority: P1)

As the kestrel operator, when a run starts working on a ticket, I want the ticket itself to show that it's being worked on, and when the run finishes — successfully or not — I want the ticket to reflect the true outcome (delivered, or something went wrong), without me having to cross-reference kestrel's own UI to know what state a ticket is really in.

**Why this priority**: This is the core ask — today a ticket gives no signal that kestrel is even working on it, or whether a run that touched it succeeded or failed. Without this, every other part of the feature (time tracking, hooks) has nothing to attach to.

**Independent Test**: Trigger a run against a real (or sandboxed) GitHub issue and a real (or sandboxed) Jira ticket. Confirm the ticket shows an "in progress" signal shortly after the run starts, and confirm it shows a "done" signal only once the run actually delivers — never on a run that fails, is escalated, or is rejected.

**Acceptance Scenarios**:

1. **Given** a ticket with no active run, **When** kestrel starts a run against it, **Then** the ticket shows an in-progress signal within a short, predictable time.
2. **Given** a run that is in progress, **When** the run completes successfully and opens a change request, **Then** the ticket shows a "done" signal and no longer shows "in progress".
3. **Given** a run that is in progress, **When** the run fails, is escalated for human attention, or is rejected, **Then** the ticket shows a signal distinct from "done" that makes clear the work did not complete successfully.
4. **Given** a task source that has no native concept of "in progress" or "done" status, **When** a run transitions through these states, **Then** kestrel still records the same information for the operator by appending it to a comment it posts on the ticket.

---

### User Story 2 - Accurate time-spent reporting (Priority: P2)

As the kestrel operator, I want to know how much genuine implementation effort a run took, separate from how long it sat waiting on me to respond to a question or approve something, so that the time I report or use for estimation reflects real work, not my own response latency.

**Why this priority**: Directly requested and valuable on its own once status sync exists, but depends on the same run lifecycle as User Story 1 rather than replacing it — it's the second, independent metric layered on the same events.

**Independent Test**: Run a task that pauses at least once for the operator's input or approval. Confirm the two reported numbers — active work time and wait time — both reflect reality: wait time covers only the time the run was genuinely parked waiting on the operator, and active time excludes it.

**Acceptance Scenarios**:

1. **Given** a run that never pauses for operator input, **When** it completes, **Then** the reported active time approximates the run's total duration and the reported wait time is zero (or negligible).
2. **Given** a run that pauses twice for operator approval, **When** it eventually completes, **Then** the reported wait time is the sum of both pauses and the reported active time excludes both pauses.
3. **Given** a task source with a native field for time-tracking, **When** a run completes, **Then** kestrel writes the active time to that native field.
4. **Given** a task source with no native time-tracking field, **When** a run completes, **Then** kestrel reports both active time and wait time in a comment footer instead.

---

### User Story 3 - Operator-defined custom actions per lifecycle event (Priority: P3)

As the kestrel operator working against a highly configurable Jira instance, I want to plug in my own scripts that run automatically whenever a run starts, finishes, or fails, so I can perform whatever custom action my specific Jira setup needs (a workflow transition kestrel doesn't know about, a custom field, a notification elsewhere) without waiting for kestrel to natively support it.

**Why this priority**: This is the escape hatch for the long tail of platform-specific configuration kestrel can never fully anticipate. It builds on User Stories 1 and 2 (the same lifecycle events) and is valuable independently of them, but is lower priority because kestrel's own built-in status/time reporting from Stories 1–2 already covers the common case without it.

**Independent Test**: Configure a script for one task source that reacts only to a "run failed" event. Trigger a failing run against that source and confirm the script executes with the event's data, while a successful run against the same source does not trigger that script's custom action (though the script itself is invoked and may no-op).

**Acceptance Scenarios**:

1. **Given** a task source with a configured script location, **When** a run reaches any lifecycle event (start, done, failed, escalated, rejected), **Then** every script found there is invoked with that event's information.
2. **Given** a task source with a configured script location, **When** kestrel also performs its own built-in status transition and/or comment footer for the same event, **Then** both the script and kestrel's own built-in behavior happen — the script never replaces or suppresses kestrel's own behavior.
3. **Given** a task source with no script location configured, **When** a run reaches a lifecycle event, **Then** no script is invoked and only kestrel's own built-in behavior occurs.
4. **Given** a script that hangs, exits with an error, or produces invalid output, **When** it is invoked for an event, **Then** the run continues normally, kestrel's own built-in behavior for that event still happens, and any other configured scripts for that event still run.
5. **Given** a script needs to call the ticket's own API (e.g. to perform a custom workflow transition), **When** it is invoked, **Then** it has access to the same credentials kestrel itself uses for that ticket's platform.

---

### Edge Cases

- A run belongs to no external ticket (a manually triggered run) — no status transition, time report, or hook is attempted, since there is no ticket to inform.
- A run pauses for operator input, the operator never responds, and the run is later abandoned/escalated — wait time must still be counted up to the point of escalation, not left unbounded or silently dropped.
- Two scripts are configured for the same task source and one of them takes an unusually long time — it must not block the other script or delay kestrel's own comment/status update indefinitely.
- A platform's native status transition succeeds but its native time-tracking write fails (or vice versa) — each is reported/handled on its own merits; a failure in one must not suppress the other or block the comment fallback.
- An operator points the script location at a location they do not fully control (e.g., a shared or externally-writable path) — because a script has access to kestrel's own credentials, this is a meaningful trust decision, and the operator must be clearly warned about it in kestrel's documentation before they can be expected to make it safely.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST transition a ticket's status to an "in progress" signal (native to the platform where supported, otherwise reported via comment) when kestrel begins working a run against it.
- **FR-002**: System MUST transition a ticket's status to a "done" signal only when the run completes successfully (i.e., a change request has been opened) — never for a run that fails, is escalated, or is rejected.
- **FR-003**: System MUST transition a ticket to a distinct, non-"done" signal when a run fails, is escalated for human attention, or is rejected, so the ticket does not remain stuck showing "in progress" indefinitely after an unsuccessful run.
- **FR-004**: System MUST attempt the platform's native mechanism for each status transition where the platform offers one (e.g. an issue label, a workflow transition), and MUST fall back to reporting the status in a footer on a comment kestrel posts whenever that native mechanism isn't successfully applied — whether because the platform has none, or because the attempt itself failed (e.g. a network error, an expired credential, a rate limit). Both cases are handled identically from the operator's perspective: the footer always carries whatever the native attempt didn't get through.
- **FR-005**: System MUST measure two independent time metrics per run: active work time (while the run is genuinely being implemented) and wait time (while the run is parked waiting on operator input or approval). Neither MUST be derived by subtracting one from the other or from total elapsed time.
- **FR-006**: System MUST report the active work time to the ticket's native time-tracking field where the platform and configuration support one, and MUST otherwise report it via a comment footer. Wait time is always reported via the comment footer; no platform gets a native field for wait time.
- **FR-007**: System MUST allow the operator to configure, per task source, a location containing executable scripts to be invoked at every lifecycle event (run start, done, failed, escalated, rejected).
- **FR-008**: System MUST invoke every configured script for a task source on every lifecycle event for that source, passing that event's information (event kind, ticket reference, active/wait time, links, and outcome details) to the script.
- **FR-009**: System MUST always perform its own built-in status transition and/or comment-footer fallback for a lifecycle event regardless of whether any scripts are configured or what they do — scripts are strictly additive and can never suppress kestrel's own status/time reporting, except that a script MAY signal it has already posted its own comment for that event, in which case kestrel skips only its own duplicate comment (not the native status/time transition, which is unaffected).
- **FR-010**: System MUST isolate script failures (non-zero exit, running longer than 30 seconds, or invalid output) so that one failing script never prevents another configured script from running, never blocks kestrel's own built-in lifecycle handling, and never interrupts the run itself. A script still running after 30 seconds MUST be treated as failed for that invocation.
- **FR-011**: System MUST give each invoked script access to the same credentials kestrel itself holds for that ticket's platform, so a script can perform its own calls against that platform's API using kestrel's own authentication.
- **FR-012**: System MUST document prominently, for the operator, that a configured script location is granted the same level of trust as kestrel's own stored credentials (FR-011), and that only locations the operator fully controls and trusts should ever be configured.
- **FR-013**: System MUST NOT expose a script's diagnostic/error output verbatim in any ticket-facing location (comments, status fields), since that output could inadvertently include sensitive information the script had access to.
- **FR-014**: System MUST make status-transition and time-tracking behavior configurable per task source, since different instances of the same platform type (e.g. two different Jira sites) may need different native field/transition mappings, or may support none at all.
- **FR-015**: System MUST behave without any of these features for a run that has no associated external ticket (e.g. a manually triggered run) — no status transition, time report, or script is attempted.
- **FR-016**: System MUST record, at startup, which scripts it found in each configured hook location, so an operator reviewing kestrel's own logs has a chance to notice a script they did not expect to be there.

### Key Entities

- **Lifecycle Event**: A moment in a run's life the ticket should be informed of — one of "started", "done", "failed", "escalated", or "rejected" — carrying the run's active time, wait time, and relevant links/outcome details at that moment.
- **Task Source**: An external ticket-tracking platform kestrel is connected to (e.g. a GitHub repository, a Jira instance), now additionally responsible for attempting native lifecycle-status and time-tracking updates, and declaring which of those it natively supports.
- **Operator Script (Hook)**: An executable the operator places in a per-task-source configured location, invoked for every lifecycle event on that source, that can perform arbitrary custom actions using kestrel's own platform credentials.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator glancing at any ticket kestrel is working on — without opening kestrel itself — can correctly tell whether kestrel hasn't started, is actively working, delivered successfully, or the run ended unsuccessfully.
- **SC-002**: For 100% of runs that reach a terminal outcome other than successful delivery, the ticket never shows a "done" signal.
- **SC-003**: After a run completes, the reported active time and wait time together account for the operator's actual experience of the run (i.e., wait time reflects genuine response-waiting periods, not implementation time), verified across runs with zero, one, and multiple approval pauses.
- **SC-004**: An operator can add a new custom action for one task source's lifecycle events without any kestrel code change or restart-affecting configuration beyond adding a script and pointing the existing per-source setting at it.
- **SC-005**: A single malfunctioning custom script never causes a run to fail, never blocks another script from running, and never prevents kestrel's own status/time reporting for that same event.
- **SC-006**: Before an operator can point kestrel at a script location for the first time, kestrel's documentation makes the credential-exposure trust implication unambiguous.
- **SC-007**: An operator reviewing kestrel's startup logs after configuring a hook location can see exactly which scripts kestrel found there, without needing to inspect the filesystem directly.

## Assumptions

- Kestrel is a single-user, operator-configured tool (per the project constitution); "the operator" is both the person configuring task sources/scripts and the sole consumer of the credentials scripts gain access to — there is no multi-tenant trust boundary to design for.
- The active-work clock starts when a run leaves its initial queued state and begins real work (e.g., provisioning/cloning), and stops the moment the run reaches any terminal outcome; provisioning overhead is treated as part of "active work" rather than tracked as a third category, since it is not time the operator spent waiting and is not worth a separate metric.
- Reporting time metrics to the operator via the ticket (native field or comment footer) satisfies the stated need; no dedicated in-app UI display of these metrics is required for this feature (a natural follow-up if requested later).
- "Done" always corresponds to a run successfully opening a change request; there is no partial or intermediate "done" state to represent.
- Sandboxing or restricting what a configured script can do (beyond the isolation/failure-containment in FR-010) is out of scope — the operator's own judgment about what to place in the configured location is the only control, consistent with how git's own hook mechanism works.

## Clarifications

### Session 2026-07-27

- Q: Should Jira additionally support writing wait time to a second native field (mirroring the native active-time field), or should wait time only ever be reported via the comment footer regardless of platform? → A: Footer-only everywhere — wait time is never written to a native platform field; only active time gets that treatment.
- Q: Should active/wait time metrics be surfaced anywhere in kestrel's own UI, or are they purely an outbound signal sent to the ticket? → A: Ticket-facing only — no in-app UI display of these metrics is part of this feature.
- Q: Should every configured script see every lifecycle event and decide for itself which ones matter (self-filtering), or should the configured location use one script per named event (e.g. a script specifically for "on completion", another specifically for "on failure")? → A: Single location, self-filtering — every script in the configured location is invoked for every lifecycle event and inspects the event data to decide whether to act.
- Q: FR-010 requires isolating a script that runs for an "excessive runtime" — how long should kestrel let one hook script run before treating that invocation as timed out? → A: 30 seconds.
- Q: If a platform has a native status/time mechanism but kestrel's attempt to use it fails (network error, expired credential, rate limit) rather than the platform simply lacking one, should that be treated the same as "unsupported" (fall back to the footer), or handled differently? → A: Treated the same — any unsuccessful native attempt, for any reason, falls back to the footer.
- Q: Given a hook script has access to kestrel's own credentials, should kestrel maintain any visible record of what scripts are present in a configured hook location, or is that entirely the operator's own responsibility? → A: Kestrel logs what it finds in each configured hook location at startup (FR-016).

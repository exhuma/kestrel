# Feature Specification: Fixture Task Source & Rerun

**Feature Branch**: `[008-fixture-task-source]`

**Created**: 2026-08-10

**Status**: Draft

**Input**: User description: "Add a file-backed \"fixture\" task source
(TaskSource + reused CodeHost) for local, disposable retry/testing of the
refine→code→verify pipeline without touching a real GitHub/Jira ticket. Add a
visibility() capability (public/private) to the TaskSource protocol; GitHub
and Jira report public, fixture reports private. Add a \"rerun\" action
(abandon + delete branch + immediately restart against the same ticket)
exposed only when the run's source is private, surfaced via a new
`rerunnable` flag on `WorkflowSummary`/`WorkflowDetail` and a Rerun button in
the workflow panel."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run a disposable task through the pipeline (Priority: P1)

As the kestrel admin, I want to define a local, disposable task and run it
through the full refine → design → code → verify pipeline, so I can test
prompt changes, config changes, or alternative backends without creating any
activity on a real GitHub issue or Jira ticket.

**Why this priority**: This is the core capability the feature exists to
provide. Without it, every pipeline experiment either pollutes a real tracker
or requires manual database surgery to fake a run.

**Independent Test**: Define a local task pointing at a real test repository,
let kestrel pick it up, and confirm a run starts and proceeds through the
pipeline exactly as a GitHub- or Jira-originated run would, with no request
ever reaching GitHub's or Jira's APIs on the task's behalf.

**Acceptance Scenarios**:

1. **Given** a local task is defined and the target repository is
   configured, **When** kestrel next checks for work, **Then** a new run
   starts for that task using the same pipeline stages as any other run.
2. **Given** a local task's wording is edited on disk between runs, **When**
   the task is used in a later run, **Then** the run reflects the updated
   wording without requiring a service restart.
3. **Given** a local task is running, **When** it reaches a step that would
   normally write back to the tracker (e.g. posting the refined description),
   **Then** that write-back is recorded locally, not sent to any external
   service.

---

### User Story 2 - Instantly restart a disposable run (Priority: P2)

As the kestrel admin, I want to discard a disposable run's in-progress work
and restart it from scratch against the same task, so I can retry after
tweaking a prompt, a config value, or the backend being used — without
waiting for the next scheduled check.

**Why this priority**: Depends on User Story 1 existing, and is what turns
"disposable tasks" into an actual retry workflow rather than a one-shot
test.

**Independent Test**: With a local-task run in any state (in progress,
failed, escalated, or complete), trigger rerun and confirm a fresh run for
the same task starts immediately, with the previous run's in-progress
branch and session state discarded.

**Acceptance Scenarios**:

1. **Given** a run originating from a local task, **When** the admin
   triggers rerun, **Then** the run's branch and in-progress work are
   discarded and a new run for the same task starts immediately, without
   waiting for the next scheduled check.
2. **Given** a run originating from a local task that already finished
   (successfully or not), **When** the admin triggers rerun, **Then** a new
   run starts the same as for an in-progress run.

---

### User Story 3 - Protect real tickets from history rewrites (Priority: P1)

As the kestrel admin, I want the "rerun" action to be unavailable for any
run that came from a real, shared tracker (GitHub or Jira), so that anyone
else who has already seen or linked to that ticket's history — a
notification email, a linked comment — never has that history disappear or
get rewritten out from under them.

**Why this priority**: This is the safety property that makes it acceptable
to offer a destructive "start over" action at all. Without this guarantee,
adding rerun would create real risk of confusing or breaking other people's
references to a public ticket. Tied with User Story 1 as foundational: the
feature is unsafe to ship without it.

**Independent Test**: With a run originating from GitHub or Jira, confirm no
rerun control is shown, and confirm attempting the action directly (bypassing
the UI) is refused.

**Acceptance Scenarios**:

1. **Given** a run originating from GitHub or Jira, **When** the admin views
   that run, **Then** no rerun control is shown.
2. **Given** a run originating from GitHub or Jira, **When** rerun is
   attempted directly (not through the shown control), **Then** the system
   refuses the action and the run is left unchanged.
3. **Given** the existing "abandon" and "clean up" actions on a GitHub- or
   Jira-originated run, **When** either is used, **Then** behavior is
   unchanged from today: the local run record is removed, but the real
   ticket and its history are never modified.

### Edge Cases

- What happens when the admin triggers rerun on a run whose local task file
  has since been deleted from disk? The rerun MUST fail with a clear error
  rather than starting a run against a task that no longer exists.
- What happens when rerun is triggered while the run is still actively being
  worked on? The in-progress work MUST be cleanly stopped before the new run
  starts, the same as the existing "abandon"/"clean up" actions already do.
- What happens when two local tasks resolve to the same identifier? The
  system MUST treat this as a configuration problem and MUST NOT silently
  merge or overwrite one task's history with the other's.
- What happens when a local task's configured target repository is
  unreachable? The run MUST fail visibly, the same as it would for any other
  source whose target repository is unreachable.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow the admin to define local, disposable tasks
  that are stored entirely on local disk rather than in an external tracker.
- **FR-002**: System MUST run a local task through the same pipeline stages,
  in the same order, as a task originating from any other source.
- **FR-003**: System MUST NOT make any request to an external ticket
  tracker (GitHub, Jira) on behalf of a local task — reads, comments, and
  status changes for a local task all stay on local disk.
- **FR-004**: System MUST let the admin specify which real code repository
  (and, optionally, branch) a local task's work should be pushed to, so its
  branches and change requests land somewhere reviewable.
- **FR-005**: System MUST pick up edits made to a local task's stored
  content the next time that task is used, without requiring a service
  restart.
- **FR-006**: System MUST offer a "rerun" action that discards a run's
  in-progress work and immediately starts a fresh run for the same task,
  without waiting for the next scheduled check.
- **FR-007**: System MUST restrict the rerun action to runs whose task
  originates from a local, disposable source. It MUST be unavailable —
  both in the UI and if attempted directly — for any run whose task
  originates from a shared, externally visible tracker.
- **FR-008**: System MUST visibly indicate, per run, whether rerun is
  available for it.
- **FR-009**: System's existing behavior for abandoning or cleaning up a run
  MUST remain unchanged for every source: those actions already never modify
  the originating ticket, and this feature MUST NOT alter that.

### Key Entities

- **Task source**: A configured origin of tasks (existing entity, e.g.
  GitHub, Jira). This feature adds a new kind of task source that is local
  and disposable, and adds a **visibility** property to every task source —
  "shared" (its tickets are externally visible and only ever move forward
  in time) or "disposable" (local, admin-only, safe to reset). Rerun is
  available only for runs from a "disposable" task source.
- **Local task**: One admin-defined, file-backed unit of work: a title, a
  description, and the code repository its changes should target. Lives
  entirely on local disk; editable and removable directly by the admin.
- **Workflow run**: The existing run entity gains a per-run indicator of
  whether rerun is available, derived from its task source's visibility.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An admin can take a local task from definition to a completed
  pipeline run with zero requests made to GitHub or Jira on that task's
  behalf.
- **SC-002**: Rerunning a local-task run starts the fresh run within
  seconds, not after waiting for the system's normal scheduled check
  interval.
- **SC-003**: 100% of runs originating from GitHub or Jira never display or
  accept a rerun action, verified across every run status (in progress,
  failed, escalated, complete).
- **SC-004**: An admin can change a local task's wording and have the next
  run reflect it without restarting kestrel.

## Assumptions

- Kestrel remains single-user/single-admin (Constitution IV); "local" and
  "disposable" both mean "visible and resettable only by that one admin,"
  not a distinct multi-user permission level.
- A local task still targets a real, reachable code repository for pushing
  branches and change requests — this feature makes the *ticket* disposable,
  not the code hosting. Fully offline code hosting is out of scope.
- Authoring and editing local tasks is done by directly editing files on
  disk; a dedicated UI for creating/editing local tasks is out of scope for
  this feature.
- Rerun is offered regardless of the run's current status (in progress,
  failed, escalated, or complete) — there is no status-based restriction
  beyond the source-visibility check.
- "Shared" task sources (GitHub, Jira) already never modify or delete the
  originating ticket via the existing abandon/clean-up actions; this
  feature adds no new restriction there, only formalizes the guarantee and
  extends it to the new rerun action.

# Feature Specification: Reliable Workflow Cleanup

**Feature Branch**: `022-reliable-workflow-cleanup`

**Created**: 2026-09-15

**Status**: Draft

**Input**: User description: "The button \"clean up workflow\" does not
reliably clean up everything. I want you analyse that issue and ensure that
everything is cleaned up. One area of particular interest is any local git
checkout and/or branch as well as any pushed branches. The cleanup must bring
us back to a state where the next poll run will pick up the task again and
process a full run. This should also clean up published PRDs, created
sub-tasks. Some task-sources do not support deleting items, in which case they
must be marked as closed. Any posted comment/feedback should be removed if
possible on a \"best-effort\" basis. This would need some form of \"memory\" of
what was done. This memory could be in the database as mapping from workflow to
artifact (one to many, one workflow can generate many artifacts). If an
artifact no longer exists on cleanup, there should be no error. The cleanup
should then also clean up that memory. This memory could also be shown on the
kestrel workflow dashboard."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fully Reset a Workflow (Priority: P1)

An operator cleans up a workflow and can rely on it leaving no work created by
that workflow behind, so the source task is eligible for a new complete run.

**Why this priority**: A partial cleanup leaves duplicate work, stale branches,
or a task that cannot be processed again.

**Independent Test**: Start a workflow that creates local, remote, and
task-source artifacts; clean it up; verify each artifact is absent or closed
where deletion is unsupported and that the next poll accepts the original task.

**Acceptance Scenarios**:

1. **Given** a workflow with a local checkout, local branch, and pushed branch,
   **When** the operator cleans it up, **Then** all of those git resources are
   removed without affecting work belonging to another workflow.
2. **Given** a workflow that published a PRD and created sub-tasks, **When** the
   operator cleans it up, **Then** each created item is deleted, or closed when
   its task source cannot delete it.
3. **Given** a completed, failed, or interrupted workflow, **When** cleanup
   succeeds, **Then** the original source task is again eligible for the next
   polling cycle and receives a complete new run.

---

### User Story 2 - Recover From Partial External Cleanup (Priority: P2)

An operator can safely retry cleanup when somebody has already manually removed
some created artifacts or when one external cleanup action fails.

**Why this priority**: Cleanup spans systems outside the application and must
remain safe and useful despite concurrent manual changes or temporary failures.

**Independent Test**: Remove a tracked artifact outside the application, then
clean up the workflow and verify it completes without an artifact-not-found
error or retained tracking record.

**Acceptance Scenarios**:

1. **Given** a tracked artifact has already been deleted, **When** cleanup runs,
   **Then** it is treated as already cleaned and its tracking record is removed.
2. **Given** removal of a non-critical comment or feedback item fails, **When**
   cleanup finishes, **Then** the primary workflow reset still succeeds and the
   operator can see that the optional removal was not completed.
3. **Given** cleanup is retried after an interruption, **When** it runs again,
   **Then** it does not fail because resources were cleaned in the earlier
   attempt.

---

### User Story 3 - Inspect Workflow Artifacts (Priority: P3)

An operator can inspect the artifacts a workflow created before or while
cleaning it up.

**Why this priority**: Visibility lets the operator understand cleanup impact
and diagnose best-effort failures without relying on hidden system state.

**Independent Test**: View a workflow that has created multiple artifact types
and verify its dashboard shows their identities and cleanup status.

**Acceptance Scenarios**:

1. **Given** a workflow has created multiple artifacts, **When** the operator
   opens its dashboard, **Then** the dashboard lists each tracked artifact and
   enough identifying information to locate it.
2. **Given** cleanup has removed an artifact, **When** cleanup completes,
   **Then** the artifact is no longer retained in the workflow's artifact list.

### Edge Cases

- A checkout currently in use cannot be removed immediately; cleanup must not
  delete unrelated work and must report the remaining cleanup failure clearly.
- A remote branch has already been deleted, is protected, or cannot be reached.
- A task source supports neither deletion nor closure for a generated item.
- An artifact was created before artifact tracking became available.
- The source task is public and must not itself be deleted or rewritten.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST record every cleanup-relevant artifact created by
  a workflow, including its artifact type, external identity, location, and
  cleanup capability or outcome.
- **FR-002**: A workflow MAY have zero or more tracked artifacts, and artifacts
  MUST remain associated with their originating workflow until successfully
  cleaned or confirmed absent.
- **FR-003**: Cleanup MUST remove a workflow's local checkout and local git
  branch when they exist, without removing resources assigned to another
  workflow.
- **FR-004**: Cleanup MUST remove a workflow's pushed branch when it exists;
  an already-absent remote branch MUST be treated as successfully cleaned.
- **FR-005**: Cleanup MUST delete workflow-created PRDs, sub-tasks, and other
  task-source artifacts when their task source supports deletion.
- **FR-006**: When a task source cannot delete a workflow-created item but can
  close it, cleanup MUST close that item instead.
- **FR-007**: Cleanup MUST make a best-effort attempt to remove workflow-posted
  comments and feedback where the task source supports removing them.
- **FR-008**: Cleanup MUST continue independent cleanup actions after an
  artifact is absent or an optional comment/feedback removal fails, and MUST
  present the operator with any unresolved failures.
- **FR-009**: Cleanup MUST remove tracking records for artifacts that have been
  successfully removed, closed, or confirmed absent.
- **FR-010**: After cleanup has completed its required actions, the system MUST
  clear or reset its local workflow state so the next poll can select the
  original task for a complete fresh run.
- **FR-011**: Cleanup MUST NOT delete, close, or otherwise rewrite the original
  source task solely to reset a workflow, including for public task sources.
- **FR-012**: The workflow dashboard MUST display artifacts currently tracked
  for the workflow, including their type, identity, and cleanup status.
- **FR-013**: The system MUST retain enough cleanup failure information for an
  operator to retry unresolved required cleanup without losing the association
  to the affected artifact.

### Key Entities

- **Workflow Artifact**: A durable record of one resource a workflow created or
  posted, its external identity, its cleanup method, and its current cleanup
  state.
- **Workflow Cleanup Result**: The outcome of a cleanup request, including the
  required resources reset, best-effort results, and any artifacts that still
  need operator attention.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In automated scenarios covering local git, remote git, PRDs,
  sub-tasks, and comments, 100% of resources that can be removed are removed by
  cleanup.
- **SC-002**: In 100% of automated scenarios where a generated item cannot be
  deleted but can be closed, cleanup leaves that item closed.
- **SC-003**: In 100% of automated scenarios with an already-absent tracked
  artifact, cleanup completes without reporting that absence as an error.
- **SC-004**: After a successful cleanup, the next polling cycle selects the
  original task for a new run in 100% of automated scenarios.
- **SC-005**: Operators can identify every still-tracked workflow artifact and
  any unresolved cleanup result from the workflow dashboard in one view.

## Assumptions

- Cleanup is scoped to artifacts demonstrably created by the selected workflow;
  it never searches for or removes similarly named untracked resources.
- Closing an item is the safe fallback only for generated items on task sources
  that expose a close operation but no delete operation.
- Failure to remove comments or feedback is non-blocking when core workflow
  resources and the task's polling eligibility have been reset.
- A failed required cleanup remains visible and retryable rather than silently
  discarding its tracking record.

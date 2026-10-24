# Research: Reliable Workflow Cleanup

## Decision: Track artifacts at the point each write succeeds

**Rationale**: Cleanup can only safely remove resources that are known to have
been created by its workflow. Recording an artifact immediately after a remote
or local write succeeds makes cleanup scoped, durable across restarts, and
retryable after a partial failure.

**Alternatives considered**:

- Reconstruct artifacts from workflow deliverables: rejected because comments,
  attachments, and external identifiers are not consistently recoverable.
- Discover resources by branch name or text sentinels: rejected because it can
  match user-owned resources and cannot safely distinguish all artifacts.

## Decision: Classify artifacts by cleanup policy

**Rationale**: The cleanup engine needs a single policy for required resources,
best-effort comments, and source items that must be closed instead of deleted.
Each tracked artifact records its cleanup action and current state.

**Alternatives considered**:

- Put provider-specific conditional logic in the cleanup endpoint: rejected
  because it duplicates adapter knowledge and cannot be reused for retries.
- Treat every failure as non-blocking: rejected because an undeleted branch or
  child task prevents a full reset and must remain actionable.

## Decision: Extend the source and code-host contracts with idempotent cleanup

**Rationale**: The workflow layer should request deletion, closure, restoration,
or comment removal without knowing GitHub, Jira, or local-task APIs. Adapter
operations treat a missing resource as success and indicate when deletion is
unsupported so the service can close it where possible.

**Alternatives considered**:

- Call provider clients directly from the workflow service: rejected because it
  breaks the task-source/code-host separation and excludes configured hosts.
- Close all created items: rejected because deletion is the requested outcome
  where providers support it and closing leaves avoidable source clutter.

## Decision: Preserve and restore a source task's pre-publication state

**Rationale**: A published PRD is a workflow artifact even when the source
adapter writes it into the source task. A pre-write snapshot permits cleanup to
return the source task to the state that a new full run would see.

**Alternatives considered**:

- Leave published PRDs on the source task: rejected because a subsequent run
  would start from workflow-generated content rather than the original task.
- Delete the source task: rejected because the original task must remain
  eligible for polling.

## Decision: Amend the public-source append-only cleanup constraint

**Rationale**: Existing governance declares cleanup local-only for public task
sources. Restoring a workflow-created PRD and removing workflow-created comments
or children is an intentional, user-requested departure. The implementation
will limit it to recorded Kestrel-owned artifacts and retain no other rewrite
capability.

**Alternatives considered**:

- Keep the current prohibition: rejected because it directly prevents reliable
  cleanup and full reruns.

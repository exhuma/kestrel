# Research: Task-Source Feedback

## Decisions

### Dedicated feedback port

**Decision**: Add `FeedbackSource` as the owner of feedback enumeration and
acknowledgement, composed from task-source and code-host adapters initially.

**Rationale**: Feedback has independent transport and lifecycle concerns.

**Alternatives considered**: Continue extending `TaskSource` and `CodeHost`.
Rejected because Jira plus GitLab demonstrates their boundaries differ.

### Gate response identity

**Decision**: Every review request carries an opaque revision token.

**Rationale**: Portable ticket comments do not reliably identify a reply.

**Alternatives considered**: Reply-only association. Rejected because Jira and
GitHub issue conversations do not share a portable reply model.

### Jira cursor

**Decision**: Make cursors adapter-owned and permit inclusive re-reads guarded
by external-id deduplication.

**Rationale**: Strict timestamp filtering loses comments created at the same
timestamp.

### Re-adoption

**Decision**: A source reopen creates a linked successor through a dedicated
ingestion path.

**Rationale**: Relaxing one-run-per-task would create runs every poll cycle.

### Translation

**Decision**: Add an explicit OpenAI-compatible translation adapter selected by
a dedicated configuration router.

**Rationale**: Translation must not consume or impersonate a workflow session.

### Retention

**Decision**: Measure monitoring from source closure with a configurable
six-month default and persist the one-time retirement notice.

**Rationale**: Workflow completion and source closure are distinct events.

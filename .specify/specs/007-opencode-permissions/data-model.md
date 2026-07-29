# Data Model

No persisted entities or schema changes are required.

## Transient Permission Request

- **Session identifier**: Associates an approval with the active OpenCode
  session.
- **Permission identifier**: Identifies the pending request to answer.
- **Response**: `once` for allowed requests or `reject` for blocked edits.
- **Failure**: A transient exception that aborts the active Kestrel turn and is
  written to the existing result event and application log.

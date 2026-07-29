# Research: OpenCode Permission Compatibility

## Decision: Use the session-scoped permission endpoint

Use `POST /session/{session-id}/permissions/{permission-id}` with a request
body containing `response`, as documented by OpenCode 1.18.7.

**Rationale**: The previous global permission-reply endpoint and `reply` body
are not supported by the target server version, leaving the server's permission
request unanswered.

**Alternatives considered**: Pinning OpenCode to 1.15.x would avoid the code
change but leaves Kestrel incompatible with the operator's current deployment.

## Decision: Fail the turn when the permission channel fails

The permission event stream is required to acknowledge a headless server's
permission prompts. Its errors, and errors sending the acknowledgement, must
fail the turn and be logged.

**Rationale**: Continuing silently leaves a pending request that can consume
the full turn timeout without producing useful work.

**Alternatives considered**: Logging and continuing does not resolve the stuck
turn. Enabling OpenCode auto-approval changes deployment policy and does not
make the integration's own failure visible.

## Decision: Preserve cancellation as non-error control flow

Cancellation of the event-stream task at the end of a completed turn remains
normal and is not logged as an error.

**Rationale**: The event stream is intentionally long lived and must be
stopped after each request completes.

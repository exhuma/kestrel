# Feedback intake — removed (was features 013 and 015)

**This feature no longer exists.** Everything this document used to
describe — steering a run in flight from a marked ticket/PR comment, the
`@kestrel approve`/`reject`/`request changes` gate-decision protocol, source
reactions/replies, translation, and child-task retirement — was implemented
entirely inside the fixed six-step workflow driver
(`describe → refine → technical_analysis → design → code → verify`). That
driver, its `FeedbackIntakeService`/`FeedbackDispatcher`/`FeedbackPollService`
pipeline, and its `/api/workflows/*` router were deleted with no data
migration as part of spec
[026-autonomous-work-board](../specs/026-autonomous-work-board/spec.md)'s
Phase 10 "clean break" (see
[Architecture](architecture.md#the-work-board-spec-026)).

There is currently **no board-domain replacement**. A handful of related
config fields (`KESTREL_FEEDBACK_MARKER`, `KESTREL_FEEDBACK_IGNORE_AUTHORS`,
`KESTREL_FEEDBACK_WINDOW_DAYS`, the `[translation]` table) still exist in `backend/app/config.py` and are
accepted at startup, but nothing reads them — see [Configuration →
Vestigial settings](configuration.md#environment-variables).

**What to use instead today:** every board workflow — however it was
created (GitHub, Jira, or a local task) — is worked entirely through the
Kestrel UI. Resolve a human gate, release or discard a quarantined security
review, and retry/cancel/reassign a card there; see
[Architecture](architecture.md#the-work-board-spec-026) for the current
domain model, and its "Current gap" section for what task-source write-back
(status comments, decomposition into child tickets, and comment-based
steering itself) is tracked as follow-on work but not yet built.

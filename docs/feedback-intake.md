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

PR and MR review feedback has **no replacement yet**; that is spec 044.

Replies on a **ticket** are a different matter. Since feature 046, kestrel
reads `@kestrel` replies on a Jira ticket and decides the open gate from
them. That is a new and much smaller design, not the old protocol: a reply
only decides a gate, and only for the person entitled to decide it. See
[Architecture → Working with kestrel on the
ticket](architecture.md#working-with-kestrel-on-the-ticket-feature-046) and
[Jira workflow](setup-jira-workflow.md#replying-on-the-ticket). It reuses
the `KESTREL_FEEDBACK_MARKER` setting. The other settings of the old
feature (`KESTREL_FEEDBACK_IGNORE_AUTHORS`, `KESTREL_FEEDBACK_WINDOW_DAYS`,
the `[translation]` table) still exist in `backend/app/config.py` and are
accepted at startup, but nothing reads them. See [Configuration →
Vestigial settings](configuration.md#environment-variables).

**What to use instead today:** every board workflow — however it was
created (GitHub, Jira, or a local task) — is worked entirely through the
Kestrel UI (a Jira request can also be answered on its ticket, see
above). Resolve a human gate, release or discard a quarantined security
review, and retry/cancel/reassign a card there; see
[Architecture](architecture.md#the-work-board-spec-026) for the current
domain model, and its "Current gap" section for what task-source write-back
(status comments, decomposition into child tickets, and steering a run in
flight from a comment) is tracked as follow-on work, and what is not yet
built.

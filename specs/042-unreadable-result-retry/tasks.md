# Tasks: Work whose result cannot be read is tried again (042)

- [X] T001 `retries.py`: `UnreadableResultError`, `retry_card`, `retries_of`, `live_attempts`, `retry_context`.
- [X] T002 Routes raise `UnreadableResultError`; dispatch retries up to the cap, then escalates; the retry prompt says why. Setting `board_unreadable_retry_cap`.
- [X] T003 Operator Retry on an open escalation with a source card.
- [X] T004 Round and draft counts skip replaced attempts.
- [X] T005 Tests, event label, docs, full gate, commit, push.

# Tasks: A released request leaves Intake; escalations stay in their phase (041)

- [X] T001 [US1] `resolve_review` resolves only a pending review, completes a released card, and bumps the revision. Discard records `screening.discarded`. The router continues the intake only on a fresh release. Tests.
- [X] T002 [US1] Migration 0034 adds `board_card.source_card_id` and completes the open cards of released reviews. Test.
- [X] T003 [US2] Escalation sites record `source_card_id`. `phases.py` places the floating kinds. Tests.
- [X] T004 Frontend event label, architecture docs, full gate, commit.

# Tasks: A failed request never reads as Done (040)

- [X] T001 [US1] `outcome_of`, outcome-aware `current_phase` and
  `phase_statuses` in `backend/app/services/board/phases.py`; tests
- [X] T002 [US1] `outcome` on the listing and the snapshot; default listing
  filter; activity `cancelled`; tests
- [X] T003 [US2] Coordinator cannot transition a failed card; a failed
  interview card holds its batch; the batch is re-checked on every dispatch;
  tests
- [X] T004 [US1] Frontend: types, attention `failed`/`cancelled`, Cancelled
  column, spine statuses, activity; tests
- [X] T005 Contract, docs; full gate; commit; push

# Tasks: The coordinator runs the interview (038)

- [X] T001 Card kinds `interview_plan`, `question_review`; code-only for the
  coordinator's free-form turns; phases; manifests (coordinator and six
  interviewing specialists)
- [X] T002 [US1] `backend/app/services/board/interview_plan.py`: envelope
  context, parse and validate, batch creation, batch-answered check,
  interview completion starts the PRD; hooks in `gates.py`; tests
- [X] T003 [US2] `backend/app/services/board/question_review.py`: ids,
  context, parse and validate, reduced artifacts, gates; routing; tests
- [X] T004 [US2] Next-round context includes questions answered by another
  profile; tests
- [X] T005 [US1] Dispatch includes the coordinator for its two card kinds;
  shared question-format instructions in the refinement envelope; prompts
- [X] T006 [US1] `gate.persona`, `awaiting.role`; frontend label; tests
- [X] T007 End-to-end test; update existing interview tests; contract; gate;
  commit

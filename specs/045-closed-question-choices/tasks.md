# Tasks: A question with a closed set of answers is a choice (045)

- [X] T001 [US1] `backend/app/services/board/questions.py`: `QUESTION_FORMAT`
  states when options are required, with single, multiple and open
  examples; `is_open`; test
- [X] T002 [US2] `backend/app/services/board/question_shaping.py`: review
  instructions for options, `parse_choices` (fail closed), `converted`
- [X] T003 [US2] `backend/app/services/board/question_review.py`: questions
  tagged open/choice in the envelope; choices applied word for word; whole
  review ignored on a bad choice; lone set with an open question is
  reviewed; card titled "Review the questions"; choices recorded; tests
- [X] T004 [US2] Coordinator prompt mentions the options step
- [X] T005 Stale header comment in `frontend/src/types/interview.ts`; gate

# M-D · Interview Subsystem — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

> **STATUS: DRAFT (task-level).** Depends on M-B (state machine,
> StepRunner) and M-C (real intake). Before execution, expand each
> task to step-level TDD detail (superpowers:writing-plans) against
> the then-current codebase.

**Goal:** Kestrel's gap-analysis step emits a schema-valid JSON
questionnaire; the web UI renders it as a rich form; answers are
captured and advance the state machine.

**Architecture:** The questionnaire schema (spec SRD §2.5) is a set
of pydantic models — the single source of truth, exported as JSON
Schema for the prompt contract. The gap-analysis step (Haiku via
ModelPolicy) is instructed to output only that JSON; a deterministic
validator parses the result event, with one bounded retry on
violation. The same machinery is reused verbatim by M-F's
mid-implementation clarification pauses.

**Tech Stack:** pydantic v2 (already present), Vue/Vuetify form
components, vitest.

## Global Constraints

Same as M-A; frontend additionally: `<script setup lang="ts">`,
vanilla `fetch` via `src/api/index.ts`, no new state libraries.

---

### Task 1: Questionnaire schema + persistence

**Files:**
- Create: `backend/app/questionnaire/__init__.py`
- Create: `backend/app/questionnaire/schema.py`
- Modify: `backend/app/persistence/tables.py` + migration
  (`questionnaire`, `answer` tables)
- Test: `backend/tests/test_questionnaire_schema.py`

**Interfaces:**
- Produces: pydantic models `Questionnaire(questionnaire_id,
  title, questions: list[Question])`, `Question(id, prompt, why,
  type, required, options)` with
  `type: Literal["single_select", "multi_select", "boolean",
  "free_text"]`; `AnswerSet(questionnaire_id,
  answers: dict[str, object])` +
  `validate_answers(q, a)` (required questions answered, option
  values legal). `questionnaire.model_json_schema()` feeds the
  prompt contract in Task 2.

- [ ] Models + answer validation implemented and round-tripped
      through the DB tables.
- [ ] Rejects: unknown option value, missing required answer,
      answer to unknown question id.
- [ ] Commit.

### Task 2: Gap-analysis step + output contract

**Files:**
- Create: `backend/app/questionnaire/gap_analysis.py`
- Create: `backend/app/questionnaire/prompts.py`
- Test: `backend/tests/test_gap_analysis.py`

**Interfaces:**
- Consumes: `StepRunner.run_step` (M-B), step name
  `"gap_analysis"` (model: haiku via policy).
- Produces: `run_gap_analysis(work_item) ->
  Questionnaire | None` — None means "no gaps, skip interview".
  Prompt embeds the issue title/body and the JSON Schema, demands
  a single fenced JSON object (or the literal `NO_GAPS`).
  Deterministic extraction+validation of the result text; on
  invalid output, exactly one retry with the validation errors
  appended; then `failed`.

- [ ] Tested with faked StepRunner outputs: valid, `NO_GAPS`,
      invalid-then-valid (retry), invalid-twice (failure).
- [ ] Orchestrator wiring: `intake → analyzing →
      awaiting_clarification` (questionnaire persisted) or straight
      to `proposing_description` on `NO_GAPS`.
- [ ] Commit.

### Task 3: Questionnaire REST endpoints

**Files:**
- Modify: `backend/app/routers/work_items.py`
- Test: `backend/tests/test_questionnaire_api.py`

**Interfaces:**
- Produces: `GET /api/work-items/{id}/questionnaire` (404 if none
  pending) and `POST /api/work-items/{id}/answers` (validates via
  Task 1, persists, fires `answers_submitted` on the state
  machine). Replaces this slice of M-B's temporary `advance`
  endpoint.

- [ ] Happy path + invalid answers (422 with per-question errors).
- [ ] Commit.

### Task 4: Frontend types + API functions

**Files:**
- Modify: `frontend/src/types/` (new `questionnaire.ts`)
- Modify: `frontend/src/api/index.ts`
- Test: `frontend/tests/api/questionnaire.test.ts`

**Interfaces:**
- Produces: TS interfaces mirroring Task 1's models exactly (field
  names are the wire contract);
  `fetchQuestionnaire(workItemId)`, `submitAnswers(workItemId,
  answers)` in the api module.

- [ ] Vitest coverage with mocked fetch.
- [ ] Commit.

### Task 5: QuestionnaireForm component

**Files:**
- Create: `frontend/src/components/QuestionnaireForm.vue`
- Create: `frontend/src/composables/useWorkItems.ts` (or extend)
- Test: `frontend/tests/components/QuestionnaireForm.test.ts`

**Interfaces:**
- Consumes: Task 4 types/api.
- Produces: renders each question type with its matching Vuetify
  control (radio group / checkboxes / switch / textarea), shows the
  `why` as a hint, enforces `required` client-side, submits via
  `submitAnswers`, emits `submitted`.

- [ ] Renders all four question types from a fixture questionnaire.
- [ ] Required enforcement blocks submit until satisfied.
- [ ] Commit.

## Verification

- Backend + frontend suites green.
- Manual E2E: open a deliberately vague sandbox issue → kestrel
  reaches `awaiting_clarification` → the form shows typed questions
  with "why" hints → submit answers → state advances to
  `proposing_description`. Verify per-step model recorded for
  gap_analysis is `haiku`.
- Tick M-D in `kestrel-roadmap.md`.

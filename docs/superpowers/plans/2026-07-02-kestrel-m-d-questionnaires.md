# M-D · Structured Questionnaires — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

> Supersedes the task-level draft
> `2026-07-01-kestrel-m-d-interview.md` (written pre-merge against
> a `work_item`/`intake`/`awaiting_clarification` state machine
> that does not exist in master). Master's real interview surface
> is the `refine` phase's `awaiting_input` loop in
> `WorkflowService` (see M-B/M-E) — this plan upgrades that loop's
> output contract from free prose to structured JSON, in place.
>
> Deviations from the original spec/draft, and why:
> - **No `questionnaire`/`answer` DB tables.** The questionnaire
>   JSON is stored in the existing `WorkflowStep.deliverable` text
>   column (same column that already holds the free-text question
>   and the refined issue) — one more shape in a column that
>   already holds arbitrary step output. A new table would
>   duplicate what M-B's `workflow_step` row already persists.
> - **No separate `gap_analysis` step / no JSON-Schema dump in the
>   prompt.** Gap-detection is already inline in the single
>   `refine` session (it asks or it doesn't); splitting it into a
>   second haiku call would cost an extra session per issue for
>   no proven benefit. The prompt embeds a short hand-written
>   example instead of `model_json_schema()` output, matching this
>   codebase's existing tag-based prompt style (`<PLAN>`,
>   `<REFINED_ISSUE>`) rather than introducing JSON Schema.
> - **No bounded LLM-side retry on malformed JSON.** If the model
>   doesn't emit a valid `<QUESTIONS>` block, the step falls back
>   to today's free-text question — zero regression risk. A
>   Sonnet-side repair retry is left for later if it proves needed
>   (`M-H` candidate).
> - **No Vuetify components.** The shipped UI
>   (`WorkflowPanel.vue`) is hand-rolled HTML + scoped CSS classes
>   (`.field`, `.btn`), not `<v-…>` components, despite Vuetify
> - **No `@vue/test-utils` / component-mount tests.** No `.vue`
>   file in this project is unit-tested today (there is no DOM test
>   environment configured); only composables and libs are. The new
>   form's one piece of real logic (required-answer checking) is
>   extracted into the already-tested `lib/questionnaire.ts`; the
>   component itself is verified by the manual E2E in Task 6,
>   matching how `WorkflowPanel.vue`/`SessionPanel.vue` are verified
>   today.
>   being registered globally. The new form follows that pattern.

**Goal:** When the refine agent has a clarifying question, it asks
via a typed JSON questionnaire; the UI renders real form controls
(radio/checkbox/textarea) instead of one free-text box; submitted
answers are validated deterministically and fed back into the same
claude session. Malformed or absent questionnaires fall back to
today's plain-text reply, so nothing regresses.

**Architecture:** `app/questionnaire.py` defines the schema
(pydantic), answer validation, and answer formatting — pure,
LLM-free code per the spec's "deterministic first" principle.
`workflow_text.py` gains `extract_questionnaire`, sitting beside
its existing `extract_refined_issue`/`extract_plan` tag-extraction
siblings. `_refine()`'s "not yet refined" branch tries the
questionnaire tag before falling back to raw text. A new
`submit_answers()` service method validates and formats answers
into the same text-prompt contract the orchestration loop already
expects, so no loop code changes. Frontend: a pure parser
(`parseQuestionnaire`) gates a new `QuestionnaireForm.vue`; on
`null` the panel keeps the existing textarea.

**Tech Stack:** pydantic v2 (already present), Vue 3
`<script setup lang="ts">` + plain HTML, vitest.

## Global Constraints

Same as M-A/M-B/M-E: 80-char lines; `uv`/`npm` only; Sphinx
docstrings + full typing; tests' docstrings start with "Ensure …";
backend commands from `backend/`, frontend from `frontend/`; no
new frontend state libraries; vanilla `fetch` via `src/api`.

---

### Task 1: Questionnaire schema, validation, formatting

**Files:**
- Create: `backend/app/questionnaire.py`
- Modify: `backend/app/services/workflow_text.py`
- Test: `backend/tests/test_questionnaire.py`

**Interfaces:**
- Produces:
  - `QuestionOption(value: str, label: str)`,
    `Question(id, prompt, why="", type, required=True,
    options=[])` with `type: Literal["single_select",
    "multi_select", "boolean", "free_text"]`,
    `Questionnaire(questions: list[Question])` — all pydantic
    `BaseModel`.
  - `AnswerValidationError(errors: dict[str, str])` (Exception
    subclass).
  - `validate_answers(q: Questionnaire, answers: dict[str,
    object]) -> None` — raises on unknown question id, missing
    required answer, or an option value not in the question's
    `options`.
  - `format_answers(q: Questionnaire, answers: dict[str, object])
    -> str` — deterministic text summary consumed as the resume
    prompt.
  - `workflow_text.extract_questionnaire(text: str) ->
    Questionnaire | None` — parses a `<QUESTIONS>…</QUESTIONS>`
    JSON block; `None` on missing tag or invalid JSON/shape.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_questionnaire.py`:

```python
"""Tests for the questionnaire schema, validation, formatting."""
from __future__ import annotations

import pytest

from app.questionnaire import (
    AnswerValidationError,
    Question,
    QuestionOption,
    Questionnaire,
    format_answers,
    validate_answers,
)


def _questionnaire() -> Questionnaire:
    return Questionnaire(
        questions=[
            Question(
                id="q1",
                prompt="Which auth flow?",
                why="The issue says 'login' but not the mechanism.",
                type="single_select",
                required=True,
                options=[
                    QuestionOption(value="oidc", label="OIDC"),
                    QuestionOption(
                        value="local", label="Local password"
                    ),
                ],
            ),
            Question(
                id="q2",
                prompt="Anything else?",
                type="free_text",
                required=False,
            ),
        ]
    )


def test_validate_accepts_valid_answers() -> None:
    """Ensure a fully valid answer set raises nothing."""
    validate_answers(
        _questionnaire(), {"q1": "oidc", "q2": "no"}
    )


def test_validate_allows_optional_question_omitted() -> None:
    """Ensure an unanswered non-required question is fine."""
    validate_answers(_questionnaire(), {"q1": "oidc"})


def test_validate_rejects_missing_required() -> None:
    """Ensure a missing required answer is rejected."""
    with pytest.raises(AnswerValidationError) as exc:
        validate_answers(_questionnaire(), {})
    assert "q1" in exc.value.errors


def test_validate_rejects_unknown_option() -> None:
    """Ensure an option value outside the list is rejected."""
    with pytest.raises(AnswerValidationError) as exc:
        validate_answers(_questionnaire(), {"q1": "saml"})
    assert "q1" in exc.value.errors


def test_validate_rejects_unknown_question_id() -> None:
    """Ensure an answer to an unknown question id is rejected."""
    with pytest.raises(AnswerValidationError) as exc:
        validate_answers(
            _questionnaire(), {"q1": "oidc", "qX": "huh"}
        )
    assert "qX" in exc.value.errors


def test_validate_multi_select_and_boolean() -> None:
    """Ensure multi_select and boolean types validate correctly."""
    q = Questionnaire(
        questions=[
            Question(
                id="m", prompt="Which?", type="multi_select",
                options=[
                    QuestionOption(value="a", label="A"),
                    QuestionOption(value="b", label="B"),
                ],
            ),
            Question(id="b", prompt="Ship it?", type="boolean"),
        ]
    )
    validate_answers(q, {"m": ["a", "b"], "b": True})
    with pytest.raises(AnswerValidationError):
        validate_answers(q, {"m": ["a", "z"], "b": True})
    with pytest.raises(AnswerValidationError):
        validate_answers(q, {"m": ["a"], "b": "yes"})


def test_format_answers_renders_labels() -> None:
    """Ensure formatting resolves option values to labels."""
    text = format_answers(
        _questionnaire(), {"q1": "oidc", "q2": "Nothing else"}
    )
    assert "Which auth flow?" in text
    assert "OIDC" in text
    assert "Nothing else" in text
```

Append to `backend/tests/test_workflow_text.py` (matching that
file's existing test style — read it first for the exact import
and helper pattern already used for `extract_plan`):

```python
from app.services.workflow_text import extract_questionnaire


def test_extract_questionnaire_parses_valid_block() -> None:
    """Ensure a well-formed QUESTIONS block parses."""
    text = (
        "Before I refine this, one question.\n"
        "<QUESTIONS>"
        '{"questions": [{"id": "q1", "prompt": "Which auth?", '
        '"type": "single_select", "required": true, '
        '"options": [{"value": "oidc", "label": "OIDC"}]}]}'
        "</QUESTIONS>"
    )
    q = extract_questionnaire(text)
    assert q is not None
    assert q.questions[0].id == "q1"


def test_extract_questionnaire_returns_none_without_tag() -> None:
    """Ensure plain prose (no tag) yields None, not an error."""
    assert extract_questionnaire("Just a question in prose.") is None


def test_extract_questionnaire_returns_none_on_bad_json() -> None:
    """Ensure a malformed block yields None, not an exception."""
    text = "<QUESTIONS>{not json}</QUESTIONS>"
    assert extract_questionnaire(text) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_questionnaire.py \
tests/test_workflow_text.py -v`
Expected: `test_questionnaire.py` FAILS with
`ModuleNotFoundError: app.questionnaire`; the three new
`test_workflow_text.py` tests FAIL with
`ImportError: cannot import name 'extract_questionnaire'`.

- [ ] **Step 3: Implement**

Create `backend/app/questionnaire.py`:

```python
"""Structured clarification questionnaires: schema, validation,
and deterministic answer formatting.

Kept LLM-free by design (spec: "deterministic first") — the model
only ever produces the JSON text; every check and every rendering
decision here is plain code.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

QuestionType = Literal[
    "single_select", "multi_select", "boolean", "free_text"
]


class QuestionOption(BaseModel):
    """One selectable option for a select-type question."""

    value: str
    label: str


class Question(BaseModel):
    """One question in a clarification questionnaire."""

    id: str
    prompt: str
    why: str = ""
    type: QuestionType
    required: bool = True
    options: list[QuestionOption] = Field(default_factory=list)


class Questionnaire(BaseModel):
    """A set of clarifying questions asked in one interview round."""

    questions: list[Question]


class AnswerValidationError(Exception):
    """Raised when a submitted answer set fails validation."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__(f"invalid answers: {errors}")


def _is_missing(value: object) -> bool:
    return value is None or value == "" or value == []


def validate_answers(
    questionnaire: Questionnaire, answers: dict[str, object]
) -> None:
    """
    Validate a submitted answer set against its questionnaire.

    :param questionnaire: The questionnaire being answered.
    :param answers: Question id -> submitted value.
    :raises AnswerValidationError: If any answer is invalid,
        with one message per offending question id.
    """
    errors: dict[str, str] = {}
    by_id = {q.id: q for q in questionnaire.questions}
    for qid in answers:
        if qid not in by_id:
            errors[qid] = "unknown question id"
    for question in questionnaire.questions:
        value = answers.get(question.id)
        if question.required and _is_missing(value):
            errors[question.id] = "answer required"
            continue
        if value is None:
            continue
        if question.type == "single_select":
            valid = {o.value for o in question.options}
            if value not in valid:
                errors[question.id] = (
                    f"must be one of {sorted(valid)}"
                )
        elif question.type == "multi_select":
            valid = {o.value for o in question.options}
            if not isinstance(value, list) or not all(
                v in valid for v in value
            ):
                errors[question.id] = (
                    f"must be a subset of {sorted(valid)}"
                )
        elif question.type == "boolean":
            if not isinstance(value, bool):
                errors[question.id] = "must be true or false"
    if errors:
        raise AnswerValidationError(errors)


def format_answers(
    questionnaire: Questionnaire, answers: dict[str, object]
) -> str:
    """
    Render a validated answer set as a deterministic prompt.

    :param questionnaire: The questionnaire that was answered.
    :param answers: Question id -> submitted value.
    :returns: Human-readable text to resume the claude session
        with, one line per question.
    """
    lines = ["ANSWERS:"]
    for question in questionnaire.questions:
        value = answers.get(question.id)
        if _is_missing(value):
            lines.append(f"- {question.prompt}: (no answer)")
            continue
        if question.type == "boolean":
            rendered = "Yes" if value else "No"
        elif question.type == "single_select":
            labels = {o.value: o.label for o in question.options}
            rendered = labels.get(str(value), str(value))
        elif question.type == "multi_select":
            labels = {o.value: o.label for o in question.options}
            rendered = ", ".join(
                labels.get(str(v), str(v)) for v in value  # type: ignore[union-attr]
            )
        else:
            rendered = str(value)
        lines.append(f"- {question.prompt}: {rendered}")
    return "\n".join(lines)
```

`backend/app/services/workflow_text.py` — add the import and the
new extractor:

```python
import json

from pydantic import ValidationError

from app.questionnaire import Questionnaire
```

(add these to the top of the file, after the existing `import re`)

```python
def extract_questionnaire(text: str) -> Questionnaire | None:
    """
    Return the questionnaire if the agent emitted the block.

    :param text: The agent's full response text.
    :returns: The parsed, validated questionnaire, or None if the
        tag is absent or its content is not valid JSON matching
        the schema.
    """
    raw = _extract_tag(text, "QUESTIONS")
    if raw is None:
        return None
    try:
        return Questionnaire.model_validate_json(raw)
    except (ValueError, ValidationError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_questionnaire.py \
tests/test_workflow_text.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full backend suite and commit**

Run: `uv run pytest -q` — all pass.

```bash
git add -A
git commit -m "feat: add questionnaire schema, validation, and formatting"
```

---

### Task 2: Refine prompt contract + service wiring

**Files:**
- Modify: `backend/app/services/workflows.py`
- Test: `backend/tests/test_workflow_service.py`

**Interfaces:**
- Consumes: `extract_questionnaire` (Task 1),
  `validate_answers`, `format_answers`,
  `AnswerValidationError` (Task 1).
- Produces: updated `REFINE_PROMPT` / `REFINE_FEEDBACK_PROMPT`;
  `_refine()` stores `step.deliverable` as the questionnaire's
  JSON (`questionnaire.model_dump_json()`) when the agent emits a
  valid `<QUESTIONS>` block, else the raw text as before;
  `WorkflowService.submit_answers(workflow_id: str,
  answers: dict[str, object]) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_workflow_service.py`:

```python
import json

from app.questionnaire import AnswerValidationError


@pytest.mark.asyncio
async def test_questionnaire_deliverable_is_structured() -> None:
    """Ensure a valid QUESTIONS block becomes the deliverable."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "Before refining:\n<QUESTIONS>"
        '{"questions": [{"id": "q1", "prompt": "Which auth?", '
        '"type": "single_select", "required": true, '
        '"options": [{"value": "oidc", "label": "OIDC"}]}]}'
        "</QUESTIONS>",
        "<REFINED_ISSUE>\nUse OIDC\n</REFINED_ISSUE>",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_input"
    )
    deliverable = svc.get(wid).steps[0].deliverable
    parsed = json.loads(deliverable)
    assert parsed["questions"][0]["id"] == "q1"

    svc.submit_answers(wid, {"q1": "oidc"})
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_approval"
    )
    assert "ANSWERS:" in runner.calls[1]["prompt"]
    assert "OIDC" in runner.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_malformed_questions_block_falls_back_to_text() -> None:
    """Ensure an invalid QUESTIONS block degrades to plain text."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<QUESTIONS>{not json}</QUESTIONS>",
        "<REFINED_ISSUE>\nok\n</REFINED_ISSUE>",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_input"
    )
    assert svc.get(wid).steps[0].deliverable == (
        "<QUESTIONS>{not json}</QUESTIONS>"
    )
    svc.reply(wid, "free text answer")
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_approval"
    )


@pytest.mark.asyncio
async def test_submit_answers_validates() -> None:
    """Ensure invalid answers raise without touching the session."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<QUESTIONS>"
        '{"questions": [{"id": "q1", "prompt": "Which?", '
        '"type": "single_select", "required": true, '
        '"options": [{"value": "oidc", "label": "OIDC"}]}]}'
        "</QUESTIONS>",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_input"
    )
    with pytest.raises(AnswerValidationError):
        svc.submit_answers(wid, {"q1": "saml"})
    assert len(runner.calls) == 1  # no further session call
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_service.py -v`
Expected: the three new tests FAIL — the deliverable is still
raw text (no structured branch yet) and
`AttributeError: 'WorkflowService' object has no attribute
'submit_answers'`.

- [ ] **Step 3: Implement**

`backend/app/services/workflows.py` — imports:

```python
from app.questionnaire import format_answers, validate_answers
from app.services.workflow_text import (
    append_sentinel,
    extract_plan,
    extract_questionnaire,
    extract_refined_issue,
    has_sentinel,
)
```

Update the two refine prompts:

```python
REFINE_PROMPT = (
    "You are refining a GitHub issue before implementation. Read the issue "
    "below and the surrounding codebase. The complete issue text is "
    "included below — do not try to fetch it with gh or other tools. If "
    "anything is ambiguous, ask ONE round of clarifying questions as a "
    "single JSON object wrapped EXACTLY in <QUESTIONS> and </QUESTIONS> "
    "tags and nothing else, matching this shape:\n"
    '{"questions": [{"id": "q1", "prompt": "...", "why": "...", '
    '"type": "single_select", "required": true, '
    '"options": [{"value": "a", "label": "Option A"}]}]}\n'
    '"type" is one of "single_select", "multi_select", "boolean", '
    '"free_text" ("options" only applies to the select types; omit it '
    "otherwise). When you have enough detail, output the complete "
    "refined issue wrapped EXACTLY in <REFINED_ISSUE> and "
    "</REFINED_ISSUE> tags and nothing else. Do not edit any "
    "files.\n\nISSUE:\n{issue}"
)
REFINE_FEEDBACK_PROMPT = (
    "The refined issue was not approved. Revise it according to this "
    "feedback. If the feedback leaves questions open, ask them as a "
    "<QUESTIONS> block per the schema above (one round). Otherwise "
    "output the complete revised issue wrapped EXACTLY in "
    "<REFINED_ISSUE> and </REFINED_ISSUE> tags and nothing else.\n\n"
    "FEEDBACK:\n{feedback}"
)
```

In `_refine()`, replace the "not yet refined" branch:

```python
                refined = extract_refined_issue(text)
                if refined is None:
                    # Not yet refined: the agent is asking a
                    # clarifying question. Prefer the structured
                    # form; fall back to raw text so a
                    # non-compliant response never blocks the run.
                    questionnaire = extract_questionnaire(text)
                    step.deliverable = (
                        questionnaire.model_dump_json()
                        if questionnaire is not None
                        else text
                    )
                    step.status = "awaiting_input"
                    run.status = "awaiting_refine_input"
                    self.workflows.save(run)
                    prompt = await (
                        self._control[run.id].replies.get()
                    )
                    continue
```

Add `submit_answers` next to `reply`:

```python
    def submit_answers(
        self, workflow_id: str, answers: dict[str, object]
    ) -> None:
        """
        Answer the pending structured questionnaire.

        Validates the answers, formats them into the same text
        contract ``reply`` uses, and resumes the refine session.

        :param workflow_id: Id of the run being answered.
        :param answers: Question id -> submitted value.
        :raises InvalidWorkflowStateError: If no questionnaire is
            pending.
        :raises AnswerValidationError: If any answer is invalid.
        """
        run = self.get(workflow_id)
        step = run.steps[0]
        if step.name != "refine" or step.status != "awaiting_input":
            raise InvalidWorkflowStateError("not awaiting a refine reply")
        questionnaire = extract_questionnaire(step.deliverable or "")
        if questionnaire is None:
            raise InvalidWorkflowStateError("no pending questionnaire")
        validate_answers(questionnaire, answers)
        prompt = format_answers(questionnaire, answers)
        self._control[workflow_id].replies.put_nowait(prompt)
```

- [ ] **Step 4: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all pass, including M-B recovery and M-E refinement
tests (the questionnaire branch only changes what `deliverable`
holds; the state machine and gate loop are untouched).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: refine step asks structured questions when possible"
```

---

### Task 3: API — submit structured answers

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routers/workflows.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_workflows_router.py`

**Interfaces:**
- Consumes: `WorkflowService.submit_answers` (Task 2),
  `AnswerValidationError` (Task 1).
- Produces: `AnswersIn(answers: dict[str, object])`;
  `POST /api/workflows/{id}/answers`; `AnswerValidationError` ->
  HTTP 422 with `{"detail": "invalid answers", "errors": {...}}`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_workflows_router.py`, extend
`_FakeService` (add alongside the existing `reject`/`reply`
methods):

```python
    def submit_answers(
        self, workflow_id: str, answers: dict[str, object]
    ) -> None:
        if workflow_id != "wf-1":
            raise WorkflowNotFoundError(workflow_id)
        if answers.get("q1") == "bad":
            raise AnswerValidationError({"q1": "must be oidc"})
        self.answers = answers
```

(add `from app.questionnaire import AnswerValidationError` to the
file's imports, and `self.answers: dict[str, object] | None =
None` to `_FakeService.__init__`)

Append:

```python
@pytest.mark.asyncio
async def test_submit_answers_ok() -> None:
    """Ensure valid answers post through to the service."""
    service = _FakeService()
    async with _client(service) as client:
        resp = await client.post(
            "/api/workflows/wf-1/answers",
            json={"answers": {"q1": "oidc"}},
        )
    assert resp.status_code == 200
    assert service.answers == {"q1": "oidc"}


@pytest.mark.asyncio
async def test_submit_answers_validation_error_is_422() -> None:
    """Ensure invalid answers map to HTTP 422 with error detail."""
    service = _FakeService()
    async with _client(service) as client:
        resp = await client.post(
            "/api/workflows/wf-1/answers",
            json={"answers": {"q1": "bad"}},
        )
    assert resp.status_code == 422
    assert resp.json()["errors"] == {"q1": "must be oidc"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflows_router.py -v`
Expected: FAIL — the route does not exist (404).

- [ ] **Step 3: Implement**

`backend/app/schemas.py` — after `RejectIn`:

```python
class AnswersIn(BaseModel):
    """Request body to answer a structured questionnaire."""

    answers: dict[str, object]
```

`backend/app/routers/workflows.py` — import `AnswersIn` and add:

```python
@router.post("/{workflow_id}/answers")
async def submit_answers(
    workflow_id: str,
    body: AnswersIn,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Submit structured answers to the pending questionnaire."""
    service.submit_answers(workflow_id, body.answers)
    return {"status": "ok"}
```

`backend/app/main.py` — import and register a handler (add
alongside the existing `InvalidWorkflowStateError` handler):

```python
from app.questionnaire import AnswerValidationError
```

```python
    @app.exception_handler(AnswerValidationError)
    async def _invalid_answers(
        request: Request, exc: AnswerValidationError
    ) -> JSONResponse:
        """Map invalid questionnaire answers to HTTP 422."""
        return JSONResponse(
            status_code=422,
            content={
                "detail": "invalid answers",
                "errors": exc.errors,
            },
        )
```

- [ ] **Step 4: Run the full backend suite**

Run: `uv run pytest -q` — all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add answers endpoint for structured questionnaires"
```

---

### Task 4: Frontend types, parser, and requirement check

**Files:**
- Create: `frontend/src/types/questionnaire.ts`
- Create: `frontend/src/lib/questionnaire.ts`
- Modify: `frontend/src/composables/useWorkflows.ts`
- Test: `frontend/tests/lib/questionnaire.test.ts`

**Interfaces:**
- Produces:
  - `QuestionType`, `QuestionOption`, `Question`, `Questionnaire`
    TS interfaces mirroring Task 1's pydantic models field-for-
    field (the wire contract).
  - `parseQuestionnaire(text: string | null) -> Questionnaire |
    null` — pure parser; `null` on anything that isn't valid JSON
    shaped like a questionnaire.
  - `allRequiredAnswered(questionnaire: Questionnaire,
    answers: Record<string, unknown>) -> boolean` — the one piece
    of real logic `QuestionnaireForm.vue` (Task 5) needs; kept
    here, not in the component, so it can be unit-tested (this
    project has no DOM test environment for mounting components).
  - `useWorkflows().submitAnswers(answers: Record<string,
    unknown>) -> Promise<void>`.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/lib/questionnaire.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import {
  allRequiredAnswered,
  parseQuestionnaire,
} from '../../src/lib/questionnaire'
import type { Questionnaire } from '../../src/types/questionnaire'

describe('parseQuestionnaire', () => {
  it('parses a valid questionnaire', () => {
    const text = JSON.stringify({
      questions: [
        {
          id: 'q1', prompt: 'Which auth?', why: '', type: 'single_select',
          required: true, options: [{ value: 'oidc', label: 'OIDC' }],
        },
      ],
    })
    const q = parseQuestionnaire(text)
    expect(q?.questions[0].id).toBe('q1')
  })

  it('returns null for plain prose', () => {
    expect(parseQuestionnaire('Which auth flow do you want?')).toBeNull()
  })

  it('returns null for null input', () => {
    expect(parseQuestionnaire(null)).toBeNull()
  })

  it('returns null when questions is missing', () => {
    expect(parseQuestionnaire(JSON.stringify({ foo: 'bar' }))).toBeNull()
  })
})

describe('allRequiredAnswered', () => {
  const questionnaire: Questionnaire = {
    questions: [
      {
        id: 'q1', prompt: 'Which auth?', why: '', type: 'single_select',
        required: true, options: [{ value: 'oidc', label: 'OIDC' }],
      },
      {
        id: 'q2', prompt: 'Anything else?', why: '', type: 'free_text',
        required: false, options: [],
      },
    ],
  }

  it('is false until the required question is answered', () => {
    expect(allRequiredAnswered(questionnaire, {})).toBe(false)
    expect(allRequiredAnswered(questionnaire, { q1: 'oidc' })).toBe(true)
  })

  it('ignores optional questions entirely', () => {
    expect(
      allRequiredAnswered(questionnaire, { q1: 'oidc', q2: '' }),
    ).toBe(true)
  })

  it('treats an empty array as missing (multi_select)', () => {
    const q: Questionnaire = {
      questions: [
        {
          id: 'm', prompt: 'Which?', why: '', type: 'multi_select',
          required: true, options: [{ value: 'a', label: 'A' }],
        },
      ],
    }
    expect(allRequiredAnswered(q, { m: [] })).toBe(false)
    expect(allRequiredAnswered(q, { m: ['a'] })).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test`
Expected: FAIL with a module-not-found error for
`../../src/lib/questionnaire`.

- [ ] **Step 3: Implement**

Create `frontend/src/types/questionnaire.ts`:

```typescript
export type QuestionType =
  | 'single_select'
  | 'multi_select'
  | 'boolean'
  | 'free_text'

export interface QuestionOption {
  value: string
  label: string
}

export interface Question {
  id: string
  prompt: string
  why: string
  type: QuestionType
  required: boolean
  options: QuestionOption[]
}

export interface Questionnaire {
  questions: Question[]
}
```

Create `frontend/src/lib/questionnaire.ts`:

```typescript
import type { Questionnaire } from '../types/questionnaire'

/**
 * Parse a step deliverable as a structured questionnaire.
 *
 * Returns null for anything that isn't valid JSON shaped like a
 * questionnaire — free-text agent messages included — so callers
 * can fall back to the plain-text reply UI without special-casing.
 */
export function parseQuestionnaire(
  text: string | null,
): Questionnaire | null {
  if (!text) return null
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    return null
  }
  if (
    typeof data === 'object' && data !== null &&
    Array.isArray((data as Questionnaire).questions)
  ) {
    return data as Questionnaire
  }
  return null
}

function isMissing(value: unknown): boolean {
  return (
    value === undefined || value === null || value === '' ||
    (Array.isArray(value) && value.length === 0)
  )
}

/** Return true once every required question has a non-empty answer. */
export function allRequiredAnswered(
  questionnaire: Questionnaire,
  answers: Record<string, unknown>,
): boolean {
  return questionnaire.questions
    .filter((q) => q.required)
    .every((q) => !isMissing(answers[q.id]))
}
```

`frontend/src/composables/useWorkflows.ts` — add next to `reply`:

```typescript
  async function submitAnswers(
    answers: Record<string, unknown>,
  ): Promise<void> {
    if (current.value)
      await api.post(`/api/workflows/${current.value.id}/answers`, {
        answers,
      })
  }
```

and add `submitAnswers` to the returned object at the bottom of
the file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test` — all pass, including the 7 new
`parseQuestionnaire`/`allRequiredAnswered` tests.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(frontend): add questionnaire types, parser, and API call"
```

---

### Task 5: QuestionnaireForm component + panel wiring

**Files:**
- Create: `frontend/src/components/QuestionnaireForm.vue`
- Modify: `frontend/src/components/WorkflowPanel.vue`

**Interfaces:**
- Consumes: `Questionnaire`/`Question` types, `parseQuestionnaire`,
  `allRequiredAnswered` (Task 4).
- Produces: `QuestionnaireForm` props `{ questionnaire:
  Questionnaire }`, emits `submit` with `Record<string,
  unknown>`. `WorkflowPanel.vue`'s `awaitingInput` block renders
  the form when `parseQuestionnaire(activeStep.deliverable)` is
  non-null, else keeps today's textarea.

No new automated test here: the form's only real logic
(`allRequiredAnswered`) is already covered in Task 4; the
component itself is presentational and is verified by the manual
E2E in Task 6, matching how every other `.vue` file in this
project is verified (there is no DOM test environment for
mounting components — see the plan header's deviation note).

- [ ] **Step 1: Implement the component**

Create `frontend/src/components/QuestionnaireForm.vue`:

```vue
<script setup lang="ts">
import { reactive, computed } from 'vue'
import type { Questionnaire } from '../types/questionnaire'
import { allRequiredAnswered } from '../lib/questionnaire'

const props = defineProps<{ questionnaire: Questionnaire }>()
const emit = defineEmits<{ submit: [answers: Record<string, unknown>] }>()

const answers = reactive<Record<string, unknown>>({})

const canSubmit = computed(() =>
  allRequiredAnswered(props.questionnaire, answers),
)

function toggleMulti(id: string, value: string, checked: boolean): void {
  const current = new Set((answers[id] as string[] | undefined) ?? [])
  if (checked) current.add(value)
  else current.delete(value)
  answers[id] = Array.from(current)
}

function onSubmit(): void {
  if (canSubmit.value) emit('submit', { ...answers })
}
</script>

<template>
  <form class="qform" @submit.prevent="onSubmit">
    <fieldset v-for="q in questionnaire.questions" :key="q.id" class="qform__q">
      <legend class="qform__prompt">
        {{ q.prompt }}<span v-if="q.required" aria-hidden="true"> *</span>
      </legend>
      <p v-if="q.why" class="qform__why mono">{{ q.why }}</p>

      <div v-if="q.type === 'single_select'" class="qform__options">
        <label v-for="o in q.options" :key="o.value" class="qform__option">
          <input type="radio" :name="q.id" :value="o.value"
            @change="answers[q.id] = o.value" />
          {{ o.label }}
        </label>
      </div>

      <div v-else-if="q.type === 'multi_select'" class="qform__options">
        <label v-for="o in q.options" :key="o.value" class="qform__option">
          <input type="checkbox" :value="o.value"
            @change="toggleMulti(q.id, o.value, ($event.target as HTMLInputElement).checked)" />
          {{ o.label }}
        </label>
      </div>

      <div v-else-if="q.type === 'boolean'" class="qform__options">
        <label class="qform__option">
          <input type="radio" :name="q.id" @change="answers[q.id] = true" />
          Yes
        </label>
        <label class="qform__option">
          <input type="radio" :name="q.id" @change="answers[q.id] = false" />
          No
        </label>
      </div>

      <textarea v-else class="field" rows="2"
        @input="answers[q.id] = ($event.target as HTMLTextAreaElement).value" />
    </fieldset>

    <button type="submit" class="btn btn--primary" :disabled="!canSubmit">
      Submit answers
    </button>
  </form>
</template>

<style scoped>
.qform { display: flex; flex-direction: column; gap: 16px; }
.qform__q { border: 1px solid var(--line); border-radius: var(--r-md);
  padding: 12px 14px; }
.qform__prompt { font-size: 13px; color: var(--text-hi); padding: 0 4px; }
.qform__why { font-size: 11.5px; color: var(--text-dim); margin: 4px 0 10px; }
.qform__options { display: flex; flex-direction: column; gap: 6px; }
.qform__option { display: flex; align-items: center; gap: 8px;
  font-size: 12.5px; color: var(--text-mid); }
</style>
```

- [ ] **Step 2: Wire into WorkflowPanel.vue**

`frontend/src/components/WorkflowPanel.vue` — import and wire:

```typescript
import QuestionnaireForm from './QuestionnaireForm.vue'
import { parseQuestionnaire } from '../lib/questionnaire'
```

```typescript
const pendingQuestionnaire = computed(() =>
  awaitingInput.value
    ? parseQuestionnaire(activeStep.value?.deliverable ?? null)
    : null,
)

async function onSubmitAnswers(
  answers: Record<string, unknown>,
): Promise<void> {
  busy.value = 'reply'
  try {
    await submitAnswers(answers)
  } finally {
    busy.value = null
  }
}
```

(destructure `submitAnswers` from `useWorkflows()` alongside the
existing `reply, approve, reject, stop`)

Replace the existing `awaitingInput` gate block:

```html
        <div class="gate" v-if="awaitingInput">
          <QuestionnaireForm v-if="pendingQuestionnaire"
            :questionnaire="pendingQuestionnaire" @submit="onSubmitAnswers" />
          <template v-else>
            <textarea v-model="answer" class="field" rows="3"
              placeholder="Answer the agent's questions…" />
            <button class="btn btn--primary" :disabled="!!busy" @click="onReply">
              {{ busy === 'reply' ? 'Sending…' : 'Send reply' }}
            </button>
          </template>
        </div>
```

- [ ] **Step 3: Run tests + typecheck**

Run: `npm test` and `npx vue-tsc -b`
Expected: all pass (unchanged test count from Task 4 — this task
adds no new automated tests), no type errors.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(frontend): render structured questionnaires as a real form"
```

---

### Task 6: Verification & docs

**Files:**
- Modify: `docs/superpowers/plans/kestrel-roadmap.md`
- Delete: `docs/superpowers/plans/2026-07-01-kestrel-m-d-interview.md`

- [ ] **Step 1: Full suites**

`cd backend && uv run pytest -q` and
`cd frontend && npm test && npx vue-tsc -b` — all green.

- [ ] **Step 2: Manual E2E (real run)**

1. Start a backend instance (migrated DB, a free port).
2. Create a workflow on a **deliberately ambiguous** sandbox
   issue (something with a genuine either/or choice, e.g. "add
   config for X" without saying where the config lives).
3. Poll until `awaiting_refine_input`; inspect the deliverable —
   confirm it is JSON matching the questionnaire shape (if the
   model instead asked in prose, that's an accepted outcome per
   the fallback design; retry with a more clearly ambiguous issue
   to get a real structured round if so).
4. In the UI: confirm typed controls render (radio/checkbox/
   textarea as appropriate) with the `why` hint visible, and the
   submit button is disabled until required questions are
   answered.
5. Submit answers; confirm the run advances to
   `awaiting_refine_input` (follow-up question) or
   `awaiting_refine_approval`, and that the resumed session
   received the `ANSWERS:` formatted text (visible in the
   telemetry feed's next `user`/`assistant` turn).
6. Reject with a free-text refinement prompt (M-E path) to
   confirm the two features compose without conflict.

- [ ] **Step 3: Docs + close**

Roadmap: tick M-D, point it at this plan, add a status-log row
(note the no-DB-table / no-JSON-Schema-dump / no-retry
deviations). Delete the superseded draft:

```bash
git rm docs/superpowers/plans/2026-07-01-kestrel-m-d-interview.md
```

```bash
git add -A
git commit -m "docs: close milestone M-D (structured questionnaires)"
```

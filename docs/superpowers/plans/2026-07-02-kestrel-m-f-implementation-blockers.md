# M-F · Implementation Blockers & Delivery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

> Supersedes the task-level draft
> `2026-07-01-kestrel-m-f-implementation.md` (written pre-merge
> against a `work_item`/orchestrator/`WorkspaceManager` stack that
> does not exist). Reconciled against master's real
> `WorkflowService`.
>
> **What's already done, requiring no new work:**
> - **Isolated workspace per run** — `_drive()` clones the repo
>   into `run.workspace` (a fresh directory per run); the old
>   draft's "worktree" requirement is met functionally today.
> - **Commit, push, open PR** — `_deliver()` already does all
>   three; `GitHubClient.create_pull_request` already defaults to
>   `draft=True`.
> - **The frontend's blocker UI** — `WorkflowPanel.vue`'s
>   `awaitingInput`/`pendingQuestionnaire`/`QuestionnaireForm`
>   wiring (M-D) already keys off *whichever* step is active, not
>   a hardcoded step name. It needs zero code changes to also
>   serve implementation blockers — this is verified, not built,
>   in Task 3.
>
> **Deviations from the old draft, and why:**
> - **No `KESTREL_BLOCKER` tag / no separate blocker schema.**
>   Reuses the exact `<QUESTIONS>` tag and `Questionnaire` schema
>   from M-D. One contract for "the agent needs input," regardless
>   of which phase raised it — less prompt surface, and the
>   frontend/API already only know about `<QUESTIONS>`.
> - **No `max_blocker_rounds` / no `blocked` outcome / no
>   conditional draft-vs-real PR.** `_refine` already loops on
>   questions with no round cap, and by the time `_deliver()` runs
>   the human has *already* approved the diff at the
>   `awaiting_implement_approval` gate — there is no "gave up,
>   ship it anyway" case to distinguish. Consistency with the
>   existing refine/plan loops over introducing a new escape
>   hatch. (A hard-stuck run with no way to abort mid-interview is
>   a pre-existing gap shared by `_refine` — out of scope here;
>   candidate for `M-H`.)
> - **No `Notifier` protocol.** Nothing consumes it yet — there is
>   no notification center (that's `M-G`), and the polling
>   `WorkflowPanel` already surfaces `pr_url`/status directly.
>   Introducing an abstraction with no consumer is exactly the
>   premature-abstraction this project avoids elsewhere. Deferred
>   to `M-G`, where the UI that would display it actually lands.
> - **No new files.** The entire gap is generalizing two
>   `WorkflowService` methods and extending one phase's prompt —
>   everything else (questionnaire schema, extraction, validation,
>   formatting, delivery) already exists from M-D/M-B.

**Goal:** During autonomous implementation, if the agent hits a
genuine blocker, it pauses with a structured question (the same
mechanism `_refine` already uses), the human answers through the
same UI, and the *same* claude session resumes — no work lost, no
new session spawned. Reaching a clean implementation, the existing
delivery path opens a PR exactly as it does today.

**Architecture:** Generalize `WorkflowService.reply`/
`submit_answers` to target *whichever* step currently has
`status == "awaiting_input"` (today hardcoded to `steps[0]`).
Extend `IMPLEMENT_PROMPT` with the same `<QUESTIONS>` contract
`REFINE_PROMPT` uses, and give `_implement()` the identical
recovery/pause/resume branch `_refine()` already has. `recover()`
needs no changes — `awaiting_implement_input` already matches its
generic `status.startswith("awaiting_")` branch.

**Tech Stack:** unchanged.

## Global Constraints

Same as M-A/M-B/M-D/M-E: 80-char lines; `uv`/`npm` only; Sphinx
docstrings + full typing; tests' docstrings start with "Ensure …";
backend commands from `backend/`.

---

### Task 1: Generalize reply/submit_answers off `steps[0]`

**Files:**
- Modify: `backend/app/services/workflows.py`
- Test: `backend/tests/test_workflow_service.py`

**Interfaces:**
- Produces: `WorkflowService._awaiting_input_step(run:
  WorkflowRun) -> WorkflowStep` — returns whichever step has
  `status == "awaiting_input"`, raising
  `InvalidWorkflowStateError("not awaiting a reply")` if none
  does. `reply()` and `submit_answers()` use it instead of
  hardcoding `run.steps[0]`. Task 2's implement blocker relies on
  this to route answers to the implement step.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_workflow_service.py`:

```python
@pytest.mark.asyncio
async def test_reply_targets_whichever_step_is_awaiting_input() -> None:
    """Ensure reply routes to a non-refine step awaiting input."""
    from app.models_workflow import WorkflowRun, WorkflowStep

    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]), _FakeGit()
    )
    run = WorkflowRun(
        id="wf", repo="o/r", issue_number=1,
        steps=[
            WorkflowStep(name="refine", status="done"),
            WorkflowStep(name="plan", status="done"),
            WorkflowStep(
                name="implement", status="awaiting_input",
                deliverable="Which file name?",
            ),
        ],
    )
    svc.workflows.create(run)
    svc._control["wf"] = svc._new_control()

    svc.reply("wf", "config.yaml")
    queued = await svc._control["wf"].replies.get()
    assert queued == "config.yaml"


@pytest.mark.asyncio
async def test_submit_answers_targets_whichever_step_is_awaiting_input() -> None:
    """Ensure submit_answers validates against the active step."""
    from app.models_workflow import WorkflowRun, WorkflowStep

    questionnaire = (
        '{"questions": [{"id": "q1", "prompt": "Which?", '
        '"type": "single_select", "required": true, '
        '"options": [{"value": "a", "label": "A"}]}]}'
    )
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]), _FakeGit()
    )
    run = WorkflowRun(
        id="wf", repo="o/r", issue_number=1,
        steps=[
            WorkflowStep(name="refine", status="done"),
            WorkflowStep(name="plan", status="done"),
            WorkflowStep(
                name="implement", status="awaiting_input",
                deliverable=questionnaire,
            ),
        ],
    )
    svc.workflows.create(run)
    svc._control["wf"] = svc._new_control()

    svc.submit_answers("wf", {"q1": "a"})
    queued = await svc._control["wf"].replies.get()
    assert "ANSWERS:" in queued
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_service.py \
-k "targets_whichever" -v`
Expected: both FAIL with `InvalidWorkflowStateError: not awaiting
a refine reply` (the current guard only accepts `steps[0]` named
`"refine"`).

- [ ] **Step 3: Implement**

In `backend/app/services/workflows.py`, replace `reply` and
`submit_answers`:

```python
    def _awaiting_input_step(self, run: WorkflowRun) -> WorkflowStep:
        """
        Return whichever step is currently awaiting a reply.

        :param run: The run to search.
        :returns: The step with status "awaiting_input".
        :raises InvalidWorkflowStateError: If no step is awaiting
            input.
        """
        for step in run.steps:
            if step.status == "awaiting_input":
                return step
        raise InvalidWorkflowStateError("not awaiting a reply")

    def reply(self, workflow_id: str, text: str) -> None:
        run = self.get(workflow_id)
        self._awaiting_input_step(run)
        self._control[workflow_id].replies.put_nowait(text)

    def submit_answers(
        self, workflow_id: str, answers: dict[str, object]
    ) -> None:
        """
        Answer whichever step's pending structured questionnaire.

        Validates the answers, formats them into the same text
        contract ``reply`` uses, and resumes that step's session.

        :param workflow_id: Id of the run being answered.
        :param answers: Question id -> submitted value.
        :raises InvalidWorkflowStateError: If no step is awaiting
            input, or it has no pending questionnaire.
        :raises AnswerValidationError: If any answer is invalid.
        """
        run = self.get(workflow_id)
        step = self._awaiting_input_step(run)
        questionnaire = parse_questionnaire_json(step.deliverable or "")
        if questionnaire is None:
            raise InvalidWorkflowStateError("no pending questionnaire")
        validate_answers(questionnaire, answers)
        prompt = format_answers(questionnaire, answers)
        self._control[workflow_id].replies.put_nowait(prompt)
```

- [ ] **Step 4: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all pass, including the existing
`test_reply_wrong_state_raises` (no step anywhere is
`awaiting_input`, so `_awaiting_input_step` still raises) and
every M-D refine-questionnaire test (refine is just one more step
that can be the awaiting one).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: route replies to whichever step awaits input"
```

---

### Task 2: Implementation blockers — pause and resume

**Files:**
- Modify: `backend/app/services/workflows.py`
- Test: `backend/tests/test_workflow_service.py`,
  `backend/tests/test_workflow_recovery.py`

**Interfaces:**
- Consumes: `extract_questionnaire` (already imported),
  `_awaiting_input_step` (Task 1).
- Produces: updated `IMPLEMENT_PROMPT`; `_implement()` recognises
  a `<QUESTIONS>` block in the result text, pausing at
  `awaiting_implement_input` with the questionnaire JSON as the
  step's deliverable, and resumes the *same* session once
  answered (via `reply` or `submit_answers` — both already route
  here after Task 1).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_workflow_service.py`:

```python
@pytest.mark.asyncio
async def test_implement_blocker_is_structured_and_resumable() -> None:
    """Ensure a mid-implementation blocker pauses and resumes."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    git = _FakeGit()
    # First implement call produces no diff (it's the blocker);
    # the second, post-answer call produces the real change.
    git.diffs = ["", "diff --git a/x b/x"]
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nStep 1\n</PLAN>",
        "<QUESTIONS>"
        '{"questions": [{"id": "q1", "prompt": "Which file name?", '
        '"type": "single_select", "required": true, '
        '"options": [{"value": "a", "label": "config.yaml"}, '
        '{"value": "b", "label": "settings.yaml"}]}]}'
        "</QUESTIONS>",
        "Implemented using config.yaml",
    ])
    svc = _service(gh, runner, git)
    wid = await svc.create("o/r", 5)

    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    svc.approve(wid)

    await _wait(
        lambda: svc.get(wid).status == "awaiting_implement_input"
    )
    deliverable = svc.get(wid).steps[2].deliverable
    parsed = json.loads(deliverable)
    assert parsed["questions"][0]["id"] == "q1"
    blocked_sid = svc.get(wid).steps[2].session_id
    plan_sid = svc.get(wid).steps[1].session_id
    assert blocked_sid == plan_sid  # implement resumed the plan session

    svc.submit_answers(wid, {"q1": "a"})
    await _wait(
        lambda: svc.get(wid).status == "awaiting_implement_approval"
    )
    assert "ANSWERS:" in runner.calls[2]["prompt"]
    assert runner.calls[2]["resume_id"] == blocked_sid
    assert "diff" in svc.get(wid).steps[2].deliverable


@pytest.mark.asyncio
async def test_implement_malformed_blocker_falls_back_to_text_reply() -> None:
    """Ensure a non-compliant blocker message still allows a reply."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    git = _FakeGit()
    git.diffs = ["", "diff --git a/x b/x"]
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nStep 1\n</PLAN>",
        "I'm not sure which approach — thoughts?",
        "Implemented",
    ])
    svc = _service(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    svc.approve(wid)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_implement_input"
    )
    assert svc.get(wid).steps[2].deliverable == (
        "I'm not sure which approach — thoughts?"
    )
    svc.reply(wid, "Use approach B")
    await _wait(
        lambda: svc.get(wid).status == "awaiting_implement_approval"
    )
```

Append to `backend/tests/test_workflow_recovery.py`:

```python
@pytest.mark.asyncio
async def test_recover_resumes_implement_blocker(
    tmp_path: Path,
) -> None:
    """Ensure a run parked mid-implementation-blocker survives restart."""
    store = _store(tmp_path)
    runner1 = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nStep 1\n</PLAN>",
        "<QUESTIONS>"
        '{"questions": [{"id": "q1", "prompt": "Which file?", '
        '"type": "single_select", "required": true, '
        '"options": [{"value": "a", "label": "A"}]}]}'
        "</QUESTIONS>",
    ])
    git1 = _FakeGit()
    git1.diffs = [""]
    svc1 = _persistent_service(
        store,
        _FakeGitHub(body="x\n\n<!-- kestrel:refined -->"),
        runner1,
        git1,
    )
    wid = await svc1.create("o/r", 5)
    await _wait(
        lambda: svc1.get(wid).status == "awaiting_plan_approval"
    )
    svc1.approve(wid)
    await _wait(
        lambda: svc1.get(wid).status == "awaiting_implement_input"
    )

    runner2 = _FakeRunner(SessionRegistry(), outputs=["Implemented"])
    git2 = _FakeGit()
    git2.diffs = ["diff --git a/x b/x"]
    svc2 = _persistent_service(
        store,
        _FakeGitHub(body="x\n\n<!-- kestrel:refined -->"),
        runner2,
        git2,
    )
    await svc2.recover()
    assert svc2.get(wid).status == "awaiting_implement_input"

    svc2.submit_answers(wid, {"q1": "a"})
    await _wait(
        lambda: svc2.get(wid).status == "awaiting_implement_approval"
    )
    svc2.approve(wid)
    await _wait(lambda: svc2.get(wid).status == "done")
    assert git2.pushed == [svc2.get(wid).branch]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_service.py \
tests/test_workflow_recovery.py -k "implement_blocker or \
implement_malformed" -v`
Expected: all three FAIL — the run reaches
`awaiting_implement_approval` directly (no blocker branch exists
yet), so it never enters `awaiting_implement_input`.

- [ ] **Step 3: Implement**

In `backend/app/services/workflows.py`, update `IMPLEMENT_PROMPT`:

```python
IMPLEMENT_PROMPT = (
    "Implement the plan you just produced. Make all necessary code "
    "edits in this repository now. If you get genuinely blocked and "
    "need a decision you cannot make yourself, ask ONE round of "
    "clarifying questions as a single JSON object wrapped EXACTLY in "
    "<QUESTIONS> and </QUESTIONS> tags and nothing else, matching "
    "this shape:\n"
    '{"questions": [{"id": "q1", "prompt": "...", "why": "...", '
    '"type": "single_select", "required": true, '
    '"options": [{"value": "a", "label": "Option A"}]}]}\n'
    '"type" is one of "single_select", "multi_select", "boolean", '
    '"free_text" ("options" only applies to the select types; omit '
    "it otherwise). Otherwise, once the implementation is complete, "
    "just stop — do not wrap your final summary in any tags."
)
```

Replace `_implement`. Unlike `_refine` — which can tell
"question" from "done" because *only* the `<REFINED_ISSUE>` tag
means done, so anything else is a question — `_implement` has no
such tag for "done" (a real diff is not taggable text). So
distinguishing "this is a blocker" (structured *or* raw-text, as
in `test_implement_malformed_blocker_falls_back_to_text_reply`)
from "this is the finished implementation" needs a different
signal: **the diff itself.** If `git diff` is empty after the run,
nothing was implemented — treat the response as a blocker;
otherwise treat it as complete regardless of what the text says.

```python
    async def _implement(self, run: WorkflowRun) -> None:
        step = run.steps[2]
        prompt: str | None
        if step.status == "awaiting_approval":
            prompt = None  # recovered at the gate: skip to it
        elif step.status == "awaiting_input":
            # Recovered mid-blocker: wait for the answer, then
            # resume the persisted claude session with it.
            prompt = await self._control[run.id].replies.get()
        else:
            prompt = IMPLEMENT_PROMPT
        model = get_policy().model_for("implement")
        step.model = model
        while True:
            if prompt is not None:
                run.status = "implementing"
                step.status = "running"
                self.workflows.save(run)
                sid = await self.runner.run_blocking(
                    prompt, run.workspace, "acceptEdits",
                    resume_id=(
                        step.session_id or run.steps[1].session_id
                    ),
                    on_session_id=lambda s: setattr(
                        step, "session_id", s
                    ),
                    model=model,
                )
                text = self._result_text(sid)
                diff = await self.git.diff(run.workspace)
                if not diff.strip():
                    # No changes yet: treat the response as a
                    # blocker, structured or raw-text.
                    questionnaire = extract_questionnaire(text)
                    step.deliverable = (
                        questionnaire.model_dump_json()
                        if questionnaire is not None
                        else text
                    )
                    step.status = "awaiting_input"
                    run.status = "awaiting_implement_input"
                    self.workflows.save(run)
                    prompt = await (
                        self._control[run.id].replies.get()
                    )
                    continue
                step.deliverable = diff
                step.status = "awaiting_approval"
                run.status = "awaiting_implement_approval"
                self.workflows.save(run)
            decision = await self._await_gate(run.id)
            if decision.approved:
                step.status = "done"
                self.workflows.save(run)
                return
            if decision.refinement is None:
                raise _Rejected()
            prompt = IMPLEMENT_FEEDBACK_PROMPT.format(
                feedback=decision.refinement
            )
```

Update `_FakeGit.diff` in `backend/tests/test_workflow_service.py`
so the blocker tests can distinguish "no changes yet" from "there
is a diff" (today it unconditionally returns a fixed string):

```python
class _FakeGit:
    def __init__(self) -> None:
        self.pushed: list[str] = []
        self.diffs: list[str] = ["diff --git a/x b/x"]

    async def clone(self, remote_url: str, dest: str) -> None: ...
    async def checkout_branch(self, dest: str, branch: str) -> None: ...
    async def commit_all(self, dest: str, message: str) -> None: ...
    async def diff(self, dest: str) -> str:
        return self.diffs.pop(0) if self.diffs else ""
    async def push(self, dest: str, branch: str) -> None:
        self.pushed.append(branch)
```

The three new tests in Step 1 already set `.diffs` to an
empty-then-real sequence on their `_FakeGit` instances, matching
this updated fake exactly. Existing tests that expect a diff on
the *first* implement call
(`test_happy_path_refine_plan_implement_pr`,
`test_reject_implement_with_refinement_reruns`) already get one
from the default `self.diffs = ["diff --git a/x b/x"]` — no
changes needed there.

- [ ] **Step 4: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: implementation blockers pause and resume like refine"
```

---

### Task 3: Verification & docs

**Files:**
- Modify: `docs/superpowers/plans/kestrel-roadmap.md`
- Delete: `docs/superpowers/plans/2026-07-01-kestrel-m-f-implementation.md`

- [ ] **Step 1: Full suite**

Run: `cd backend && uv run pytest -q` — all green. (No frontend
changes in this milestone — Task 3's manual E2E is what proves
the existing UI already handles this; skip `npm test`/`vue-tsc`
unless something looks off.)

- [ ] **Step 2: Manual E2E (real run, through the browser)**

1. Ensure the browser's target backend (port 8001, per prior
   milestones) is running the latest code; restart it if not,
   confirming `recover()` reloads any in-flight runs.
2. Update the sandbox issue with a body that both refine and plan
   can resolve cleanly, but that pointedly instructs the
   *implementer* to defer one concrete decision and ask before
   writing code — e.g. "Add a `/ping` endpoint returning a
   timestamp. In your plan, explicitly leave the timestamp format
   (ISO-8601 vs. Unix epoch) as an implementation-time decision,
   and instruct whoever implements it to ask via a clarifying
   question before choosing."
3. Create the workflow; approve refine and plan normally.
4. Watch for `awaiting_implement_input`. If the model instead
   just picks a format and finishes (equally valid model
   behaviour — the fallback and structural correctness are
   already unit-tested against fakes), reject with feedback
   asking it to ask first, or simply record this as an accepted
   outcome and note it in the status log rather than forcing a
   live blocker at all cost.
5. If a blocker does fire: confirm in the browser that the
   *same* `QuestionnaireForm`/textarea UI used for refine renders
   it correctly with no code changes, answer it, and confirm the
   run resumes the *same* session (same session id in the
   telemetry feed) and reaches `awaiting_implement_approval`.
6. Approve the implementation; confirm the run reaches `done` and
   a **real PR** opens (draft, per today's default). Do not merge
   it — leave it for human review, consistent with the project's
   design.
7. Restart the backend while parked at `awaiting_implement_input`
   (if reached) or `awaiting_implement_approval`; confirm
   `recover()` restores the correct state and the run can still
   be advanced afterward.

- [ ] **Step 3: Docs + close**

Roadmap: tick M-F, point it at this plan, add a status-log row
(note the diff-emptiness blocker-detection heuristic and the
deferred-Notifier deviation). Delete the superseded draft:

```bash
git rm docs/superpowers/plans/2026-07-01-kestrel-m-f-implementation.md
```

```bash
git add -A
git commit -m "docs: close milestone M-F (implementation blockers)"
```

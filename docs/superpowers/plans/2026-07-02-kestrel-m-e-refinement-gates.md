# M-E · Reject-with-Refinement Gates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

> Supersedes the task-level draft
> `2026-07-01-kestrel-m-e-gates.md` (written pre-merge). Master
> already has both gates and issue write-back; this plan adds the
> missing piece — the refine loop — on top of M-B's durable,
> resumable phases. Deviation from the draft: no separate
> `proposal` table; the step's deliverable is overwritten and the
> full history remains auditable in the session's event log.

**Goal:** Rejecting a gate with a refinement prompt sends the
feedback back into the *same* claude session, which regenerates
the deliverable and returns to the same gate; rejecting without a
prompt stays terminal.

**Architecture:** `_Decision` grows a `refinement` field.  Each
phase (`_refine`, `_plan`, `_implement`) becomes a
generate → gate → (approve | reject | regenerate-with-feedback)
loop; regeneration resumes the phase's persisted session
(`--resume`), so context and quota are preserved. All three gates
get the loop. M-B's checkpoints and recovery dispatch keep working
because the loop re-uses the same persisted statuses.

**Tech Stack:** unchanged (FastAPI, pytest; Vue/Vuetify-less
Mission Control CSS, vitest).

## Global Constraints

Same as M-B: 80-char lines; `uv`/`npm` only; Sphinx docstrings +
full typing; tests' docstrings start with "Ensure …"; backend
commands from `backend/`, frontend from `frontend/`.

---

### Task 1: Refinement decisions through the service gates

**Files:**
- Modify: `backend/app/services/workflows.py`
- Test: `backend/tests/test_workflow_service.py`

**Interfaces:**
- Consumes: M-B's resumable phases and `_await_gate`.
- Produces:
  - `_Decision(approved, deliverable=None, refinement=None)`.
  - `WorkflowService.reject(workflow_id: str,
    refinement_prompt: str | None = None)`.
  - Prompt templates `REFINE_FEEDBACK_PROMPT`,
    `PLAN_FEEDBACK_PROMPT`, `IMPLEMENT_FEEDBACK_PROMPT`
    (each with a `{feedback}` slot).
  - `_FakeRunner.calls` entries additionally record `"prompt"`.

- [ ] **Step 1: Extend the fake and write the failing tests**

In `backend/tests/test_workflow_service.py`, add `"prompt"` to
the recorded call dict in `_FakeRunner.run_blocking`:

```python
        self.calls.append(
            {"resume_id": resume_id, "model": model,
             "permission_mode": permission_mode,
             "prompt": prompt}
        )
```

Append these tests:

```python
@pytest.mark.asyncio
async def test_reject_with_refinement_regenerates() -> None:
    """Ensure gate feedback loops back into the same session."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<REFINED_ISSUE>\nv1\n</REFINED_ISSUE>",
        "<REFINED_ISSUE>\nv2 with feedback\n</REFINED_ISSUE>",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_approval"
    )
    first_sid = svc.get(wid).steps[0].session_id
    svc.reject(wid, refinement_prompt="Mention the API surface")
    await _wait(
        lambda: svc.get(wid).steps[0].deliverable
        == "v2 with feedback"
    )
    assert svc.get(wid).status == "awaiting_refine_approval"
    assert runner.calls[1]["resume_id"] == first_sid
    assert "Mention the API surface" in runner.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_refinement_feedback_can_reopen_questions() -> None:
    """Ensure a feedback round may ask a new question."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<REFINED_ISSUE>\nv1\n</REFINED_ISSUE>",
        "Which API version?",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_approval"
    )
    svc.reject(wid, refinement_prompt="Cover versioning")
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_input"
    )
    assert (
        svc.get(wid).steps[0].deliverable
        == "Which API version?"
    )


@pytest.mark.asyncio
async def test_reject_plan_with_refinement_regenerates() -> None:
    """Ensure plan feedback resumes the plan session."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "plan v1", "plan v2",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_plan_approval"
    )
    plan_sid = svc.get(wid).steps[1].session_id
    svc.reject(wid, refinement_prompt="Split into two phases")
    await _wait(
        lambda: svc.get(wid).steps[1].deliverable == "plan v2"
    )
    assert svc.get(wid).status == "awaiting_plan_approval"
    assert runner.calls[1]["resume_id"] == plan_sid
    assert "Split into two phases" in runner.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_reject_implement_with_refinement_reruns() -> None:
    """Ensure implement feedback resumes the implement session."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "plan", "impl v1", "impl v2",
    ])
    git = _FakeGit()
    svc = _service(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_plan_approval"
    )
    svc.approve(wid)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_implement_approval"
    )
    impl_sid = svc.get(wid).steps[2].session_id
    svc.reject(wid, refinement_prompt="Add tests for X")
    await _wait(
        lambda: len(runner.calls) == 3
        and svc.get(wid).status
        == "awaiting_implement_approval"
    )
    assert runner.calls[2]["resume_id"] == impl_sid
    assert "Add tests for X" in runner.calls[2]["prompt"]
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_service.py -v`
Expected: the four new tests FAIL with `TypeError: reject() got
an unexpected keyword argument 'refinement_prompt'`; all
pre-existing tests still pass.

- [ ] **Step 3: Implement**

In `backend/app/services/workflows.py`:

Add after `IMPLEMENT_PROMPT` (and extend `REFINE_PROMPT`'s first
paragraph with the no-tools line):

```python
REFINE_PROMPT = (
    "You are refining a GitHub issue before implementation. Read "
    "the issue below and the surrounding codebase. The complete "
    "issue text is included below — do not try to fetch it with "
    "gh or other tools. Ask clarifying, interview-style questions "
    "ONE round at a time. When you have enough detail, output the "
    "complete refined issue wrapped EXACTLY in <REFINED_ISSUE> "
    "and </REFINED_ISSUE> tags and nothing else. Do not edit any "
    "files.\n\nISSUE:\n{issue}"
)
```

```python
REFINE_FEEDBACK_PROMPT = (
    "The refined issue was not approved. Revise it according to "
    "this feedback. If the feedback leaves questions open, ask "
    "them (one round). Otherwise output the complete revised "
    "issue wrapped EXACTLY in <REFINED_ISSUE> and "
    "</REFINED_ISSUE> tags and nothing else.\n\n"
    "FEEDBACK:\n{feedback}"
)
PLAN_FEEDBACK_PROMPT = (
    "The plan was not approved. Revise it according to this "
    "feedback and output the complete revised plan wrapped "
    "EXACTLY in <PLAN> and </PLAN> tags and nothing else. Do "
    "not edit any files.\n\nFEEDBACK:\n{feedback}"
)
IMPLEMENT_FEEDBACK_PROMPT = (
    "The implementation was not approved. Address this feedback "
    "by editing the repository now.\n\nFEEDBACK:\n{feedback}"
)
```

`_Decision` and `reject`:

```python
@dataclass
class _Decision:
    approved: bool
    deliverable: str | None = None
    refinement: str | None = None
```

```python
    def reject(
        self,
        workflow_id: str,
        refinement_prompt: str | None = None,
    ) -> None:
        """
        Reject the current gate.

        With a refinement prompt the phase regenerates its
        deliverable from the same session; without one the run
        ends as rejected.
        """
        self._resolve(
            workflow_id,
            _Decision(False, refinement=refinement_prompt),
        )
```

Replace `_refine` and delete `_refine_finalize`:

```python
    async def _refine(
        self, run: WorkflowRun, body: str | None = None
    ) -> None:
        step = run.steps[0]
        sid = step.session_id
        prompt: str | None
        if step.status == "awaiting_approval":
            prompt = None  # recovered at the gate: skip to it
        elif step.status == "awaiting_input":
            prompt = await self._control[run.id].replies.get()
        else:
            if body is None:
                raise InvalidWorkflowStateError(
                    "fresh refine needs the issue body"
                )
            prompt = REFINE_PROMPT.format(issue=body)
        model = get_policy().model_for("refine")
        step.model = model
        while True:
            if prompt is not None:
                run.status = "refining"
                step.status = "running"
                self.workflows.save(run)
                sid = await self.runner.run_blocking(
                    prompt, run.workspace, "plan",
                    resume_id=sid,
                    on_session_id=lambda s: setattr(
                        step, "session_id", s
                    ),
                    model=model,
                )
                text = self._result_text(sid)
                refined = extract_refined_issue(text)
                if refined is None:
                    # Question round: surface it and wait.
                    step.deliverable = text
                    step.status = "awaiting_input"
                    run.status = "awaiting_refine_input"
                    self.workflows.save(run)
                    prompt = await (
                        self._control[run.id].replies.get()
                    )
                    continue
                step.deliverable = refined
                step.status = "awaiting_approval"
                run.status = "awaiting_refine_approval"
                self.workflows.save(run)
            decision = await self._await_gate(run.id)
            if decision.approved:
                final = decision.deliverable or (
                    step.deliverable or ""
                )
                await self.github.update_issue(
                    run.repo, run.issue_number,
                    append_sentinel(final),
                )
                step.deliverable = final
                step.status = "done"
                self.workflows.save(run)
                return
            if decision.refinement is None:
                raise _Rejected()
            prompt = REFINE_FEEDBACK_PROMPT.format(
                feedback=decision.refinement
            )
```

Replace `_plan`:

```python
    async def _plan(self, run: WorkflowRun) -> None:
        step = run.steps[1]
        refined = run.steps[0].deliverable or ""
        prompt: str | None
        if step.status == "awaiting_approval":
            prompt = None
        else:
            prompt = PLAN_PROMPT.format(issue=refined)
        model = get_policy().model_for("plan")
        step.model = model
        while True:
            if prompt is not None:
                run.status = "planning"
                step.status = "running"
                self.workflows.save(run)
                sid = await self.runner.run_blocking(
                    prompt, run.workspace, "plan",
                    resume_id=step.session_id,
                    on_session_id=lambda s: setattr(
                        step, "session_id", s
                    ),
                    model=model,
                )
                text = self._result_text(sid)
                # Prefer the tagged block; fall back to the raw
                # text so a run still gets a reviewable
                # deliverable if the model doesn't comply.
                step.deliverable = extract_plan(text) or text
                step.status = "awaiting_approval"
                run.status = "awaiting_plan_approval"
                self.workflows.save(run)
            decision = await self._await_gate(run.id)
            if decision.approved:
                step.status = "done"
                self.workflows.save(run)
                return
            if decision.refinement is None:
                raise _Rejected()
            prompt = PLAN_FEEDBACK_PROMPT.format(
                feedback=decision.refinement
            )
        # implement resumes this plan session via
        # run.steps[1].session_id.
```

Replace `_implement`:

```python
    async def _implement(self, run: WorkflowRun) -> None:
        step = run.steps[2]
        prompt: str | None
        if step.status == "awaiting_approval":
            prompt = None
        else:
            prompt = IMPLEMENT_PROMPT
        model = get_policy().model_for("implement")
        step.model = model
        while True:
            if prompt is not None:
                run.status = "implementing"
                step.status = "running"
                self.workflows.save(run)
                await self.runner.run_blocking(
                    prompt, run.workspace, "acceptEdits",
                    resume_id=(
                        step.session_id
                        or run.steps[1].session_id
                    ),
                    on_session_id=lambda s: setattr(
                        step, "session_id", s
                    ),
                    model=model,
                )
                step.deliverable = await self.git.diff(
                    run.workspace
                )
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

- [ ] **Step 4: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all pass (incl. M-B recovery tests — the loops keep
the same persisted statuses the recovery dispatch relies on).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: reject-with-refinement loops on all gates"
```

---

### Task 2: API — reject carries an optional refinement prompt

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/routers/workflows.py:95-102`
- Test: `backend/tests/test_workflows_router.py`

**Interfaces:**
- Consumes: `WorkflowService.reject(workflow_id,
  refinement_prompt=None)` (Task 1).
- Produces: `RejectIn(refinement_prompt: str | None = None)`;
  `POST /api/workflows/{id}/reject` accepts
  `{"refinement_prompt": "…" | null}` (empty body no longer
  valid — the frontend always sends JSON).

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_workflows_router.py`: update the fake
service's `reject` to record its arguments —

```python
    def reject(
        self, workflow_id: str,
        refinement_prompt: str | None = None,
    ) -> None:
        self.rejected = (workflow_id, refinement_prompt)
```

(add `self.rejected = None` to its `__init__` if it has one,
otherwise rely on the attribute being set by the call) — and add:

```python
@pytest.mark.asyncio
async def test_reject_forwards_refinement_prompt() -> None:
    """Ensure reject passes the refinement prompt through."""
    service = _FakeService()
    async with _client(service) as client:
        resp = await client.post(
            "/api/workflows/wf-1/reject",
            json={"refinement_prompt": "tighten scope"},
        )
    assert resp.status_code == 200
    assert service.rejected == ("wf-1", "tighten scope")


@pytest.mark.asyncio
async def test_reject_without_prompt_is_terminal() -> None:
    """Ensure a bare reject forwards None."""
    service = _FakeService()
    async with _client(service) as client:
        resp = await client.post(
            "/api/workflows/wf-1/reject", json={}
        )
    assert resp.status_code == 200
    assert service.rejected == ("wf-1", None)
```

(use the file's actual fake-service class name; `_client` is the
existing helper at line 52)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_workflows_router.py -v`
Expected: new tests FAIL (endpoint takes no body / fake records
nothing).

- [ ] **Step 3: Implement**

`backend/app/schemas.py` — after `ApproveIn`:

```python
class RejectIn(BaseModel):
    """Request body to reject a gate.

    With a refinement prompt the deliverable is regenerated;
    without one the run ends as rejected.
    """

    refinement_prompt: str | None = None
```

`backend/app/routers/workflows.py` — import `RejectIn` and:

```python
@router.post("/{workflow_id}/reject")
async def reject_workflow(
    workflow_id: str,
    body: RejectIn,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Reject the current gate, optionally with feedback."""
    service.reject(workflow_id, body.refinement_prompt)
    return {"status": "ok"}
```

- [ ] **Step 4: Run the full backend suite**

Run: `uv run pytest -q` — all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: reject endpoint accepts a refinement prompt"
```

---

### Task 3: Frontend — "Request changes" gate action

**Files:**
- Modify: `frontend/src/composables/useWorkflows.ts:75-77`
- Modify: `frontend/src/components/WorkflowPanel.vue`
- Test: `frontend/tests/composables/useWorkflows.test.ts`

**Interfaces:**
- Consumes: Task 2's `RejectIn` wire shape.
- Produces: `reject(refinementPrompt?: string)` in the
  composable; a third gate action in the panel.

- [ ] **Step 1: Write the failing test**

Append to `frontend/tests/composables/useWorkflows.test.ts`
(inside the existing `describe`):

```typescript
  it('reject sends the refinement prompt', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const wf = useWorkflows()
    // a current run must be selected for reject() to post
    wf.current.value = {
      id: 'wf-1', repo: 'o/r', issue_number: 1, issue_title: 't',
      status: 'awaiting_plan_approval', branch: 'b', steps: [],
      current_session_id: null, pr_url: null, error: null,
    }
    await wf.reject('tighten scope')
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/workflows/wf-1/reject')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      refinement_prompt: 'tighten scope',
    })
    await wf.reject()
    const [, init2] = fetchMock.mock.calls[1]
    expect(JSON.parse((init2 as RequestInit).body as string)).toEqual({
      refinement_prompt: null,
    })
  })
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test`
Expected: FAIL — body is `{}` (current signature takes no args).

- [ ] **Step 3: Implement**

`frontend/src/composables/useWorkflows.ts`:

```typescript
  async function reject(refinementPrompt?: string): Promise<void> {
    if (current.value)
      await api.post(`/api/workflows/${current.value.id}/reject`, {
        refinement_prompt: refinementPrompt ?? null,
      })
  }
```

`frontend/src/components/WorkflowPanel.vue` — script additions:

```typescript
const feedback = ref('')
```

change the `busy` union:

```typescript
const busy = ref<'create' | 'approve' | 'reject' | 'reply'
  | 'changes' | null>(null)
```

add the handler (next to `onReject`):

```typescript
async function onRequestChanges(): Promise<void> {
  busy.value = 'changes'
  try {
    await reject(feedback.value)
    feedback.value = ''
  } finally {
    busy.value = null
  }
}
```

template — extend the approval gate block (`v-if="awaitingApproval"`)
below the existing Approve/Reject actions:

```html
          <textarea v-model="feedback" class="field" rows="3"
            placeholder="Or describe what to change and send it back…" />
          <button class="btn" :disabled="!feedback.trim() || !!busy"
            @click="onRequestChanges">
            {{ busy === 'changes' ? 'Sending…' : 'Request changes' }}
          </button>
```

- [ ] **Step 4: Run tests + typecheck**

Run: `npm test` and `npx vue-tsc -b`
Expected: all pass, no type errors.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(frontend): request-changes action on approval gates"
```

---

### Task 4: Verification & docs

**Files:**
- Modify: `docs/superpowers/plans/kestrel-roadmap.md`
- Delete: `docs/superpowers/plans/2026-07-01-kestrel-m-e-gates.md`

- [ ] **Step 1: Full suites**

`cd backend && uv run pytest -q` and
`cd frontend && npm test` — all green.

- [ ] **Step 2: Manual E2E (real run)**

1. Start a backend instance (port 8321, migrated DB).
2. Create a workflow on the sandbox issue; drive it to
   `awaiting_refine_approval` (answer a question round if asked).
3. `POST …/reject` with
   `{"refinement_prompt": "<some concrete change>"}` → verify the
   run returns to `refining` then `awaiting_refine_approval` with
   a **changed deliverable**, and the step's `session_id` is
   unchanged (same session resumed).
4. Reject with `{}` → run ends `rejected`.
5. In the UI: confirm the gate shows Approve / Reject and the
   Request-changes textarea+button, and that the awaiting pulse
   still fires.

- [ ] **Step 3: Docs + close**

Roadmap: tick M-E, point it at this plan, add a status-log row
(note the no-proposal-table deviation). Delete the superseded
draft (`git rm docs/superpowers/plans/2026-07-01-kestrel-m-e-gates.md`).

```bash
git add -A
git commit -m "docs: close milestone M-E (refinement gates)"
```

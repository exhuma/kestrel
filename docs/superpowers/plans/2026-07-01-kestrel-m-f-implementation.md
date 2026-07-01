# M-F · Autonomous Implementation & PR — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

> **STATUS: DRAFT (task-level).** Depends on M-B..M-E. Before
> execution, expand each task to step-level TDD detail
> (superpowers:writing-plans) against the then-current codebase.

**Goal:** On plan approval, kestrel implements the plan hands-off in
an isolated worktree, pauses for a structured clarification when
genuinely blocked, resumes on answer, then commits, pushes, opens a
PR (draft if a blocker stayed unresolved), and notifies the user.

**Architecture:** The implement step runs via StepRunner (Sonnet by
default) with `cwd` = the M-C worktree, so global MCP servers and
the Max login apply as in the spike. Blockers use an *output
contract*: the prompt instructs claude that, when blocked, it must
emit a single `KESTREL_BLOCKER` JSON object matching the M-D
questionnaire schema and stop. Pause/resume reuses the spike's
proven `--resume` + same-cwd mechanic; answers are injected as the
resume prompt. Git/PR/notify are deterministic. The `Notifier`
protocol is introduced here (spec §2.2) with a minimal persisted
back-end; the UI notification center follows in M-G.

**Tech Stack:** as before; git via `WorkspaceManager` (M-C); PR via
`GitHubSource.open_pr` (M-C).

## Global Constraints

Same as M-A. Implementation sessions keep
`--permission-mode acceptEdits` (spike-verified).

---

### Task 1: Implement step in a worktree

**Files:**
- Create: `backend/app/orchestrator/implement.py`
- Modify: `backend/app/services/runner.py` (allow explicit `cwd`
  for `start`, keeping the default behaviour)
- Test: `backend/tests/test_implement_step.py`

**Interfaces:**
- Consumes: `WorkspaceManager.ensure_worktree` (M-C), `StepRunner`
  (step `"implement"`), approved plan body (M-E).
- Produces: `run_implementation(work_item) -> ImplementOutcome`
  where outcome is `completed | blocked | failed`; prompt embeds
  the approved plan + refined description + the blocker contract.

- [ ] Faked-runner tests for all three outcomes; asserts session
      cwd is the worktree path.
- [ ] Commit.

### Task 2: Blocker contract + detection

**Files:**
- Create: `backend/app/orchestrator/blockers.py`
- Test: `backend/tests/test_blockers.py`

**Interfaces:**
- Consumes: questionnaire schema + validation (M-D Task 1) —
  reused verbatim.
- Produces: `detect_blocker(final_text) -> Questionnaire | None`
  (extracts the `KESTREL_BLOCKER` JSON block, validates); on
  detection: state → `paused_for_clarification`, questionnaire
  persisted, session id retained for resume.

- [ ] Detection tests: clean completion, well-formed blocker,
      malformed blocker JSON (→ `failed`, raw text persisted for
      debugging).
- [ ] Commit.

### Task 3: Pause → answer → resume loop

**Files:**
- Modify: `backend/app/orchestrator/service.py`
- Test: `backend/tests/test_pause_resume.py`

**Interfaces:**
- Consumes: M-D's `POST /answers` endpoint (same endpoint serves
  mid-run blockers — no new API), spike-verified
  `SessionRunner.resume`.
- Produces: `answers_submitted` in `paused_for_clarification`
  formats the answers into a resume prompt and continues the *same*
  claude session in the same worktree; loop bounded by
  `max_blocker_rounds` setting (default 3) → beyond it, outcome
  `blocked` (draft PR path).

- [ ] Tests: single pause/resume round-trip (faked runner asserts
      `--resume <original session id>`), round-limit exhaustion.
- [ ] Commit.

### Task 4: Commit, push, PR

**Files:**
- Create: `backend/app/orchestrator/delivery.py`
- Test: `backend/tests/test_delivery.py`

**Interfaces:**
- Consumes: `WorkspaceManager.push` (M-C),
  `GitHubSource.open_pr` (M-C).
- Produces: `deliver(work_item, outcome) -> str` (PR URL):
  verifies the worktree has commits (claude commits during the
  session; if it left uncommitted changes, commit them
  deterministically as `chore: kestrel checkpoint`), pushes the
  `kestrel/issue-<n>` branch, opens the PR — **draft** when
  outcome is `blocked`, with the unresolved blocker quoted in the
  PR body; links the PR on the work item; state → `done`.

- [ ] Local-fixture-repo tests: normal PR, draft-on-blocked,
      nothing-to-deliver (→ `failed`).
- [ ] Commit.

### Task 5: Notifier protocol + minimal back-end

**Files:**
- Create: `backend/app/notifications/__init__.py`
- Create: `backend/app/notifications/base.py`
- Create: `backend/app/notifications/inapp.py`
- Modify: `backend/app/persistence/tables.py` + migration
  (`notification` table: id, work_item_id, kind, message, url,
  read, created_at)
- Test: `backend/tests/test_notifications.py`

**Interfaces:**
- Produces: `Notifier` protocol —
  `notify(event: str, work_item_id: int,
  payload: dict[str, object]) -> None` — and
  `InAppNotifier` persisting rows; back-ends registered from
  config (`KESTREL_NOTIFIERS`, default `["inapp"]`). Orchestrator
  calls it at: input needed (questionnaire/approval), PR ready,
  item failed. M-G adds the UI; M-H adds more back-ends.

- [ ] Protocol-conformance + persistence tests; orchestrator emits
      on the three trigger kinds.
- [ ] Commit.

## Verification

- Suites green.
- Manual E2E (the big one): sandbox issue → interview → approved
  description → approved plan → watch implementation run hands-off
  in its worktree → **confirm a real PR opens** with sensible
  commits, and a notification row exists. Then force a blocker
  (issue asking for an impossible/ambiguous change) → confirm
  pause, answer via the form, confirm resume and eventual (draft)
  PR.
- Restart the backend while `paused_for_clarification`; answer
  after restart must still resume the correct session.
- Tick M-F in `kestrel-roadmap.md`.

# M-E · Proposal & Approval Gates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

> **STATUS: DRAFT (task-level).** Depends on M-B/M-C/M-D. Before
> execution, expand each task to step-level TDD detail
> (superpowers:writing-plans) against the then-current codebase.

**Goal:** The two human gates: kestrel proposes a refined issue
description and later an implementation plan; the user approves,
rejects, or rejects-with-refinement-prompt; approved descriptions
are written back to the GitHub issue; approved plans trigger
implementation.

**Architecture:** One generic proposal mechanism serves both gates:
a `proposal` row (`kind: "description" | "plan"`, markdown body,
status, refinement history). Proposal generation is a Sonnet step
via StepRunner; the refine loop *resumes the same claude session*
(`--resume`) with the user's refinement prompt, keeping full
context. Approval/rejection endpoints fire state-machine events;
approval side-effects (GitHub write-back, start implementation) are
deterministic orchestrator code.

**Tech Stack:** as before; markdown rendering in the frontend (small
md renderer, no heavyweight editor).

## Global Constraints

Same as M-A/M-D.

---

### Task 1: Proposal model + persistence

**Files:**
- Modify: `backend/app/persistence/tables.py` + migration
  (`proposal` table: id, work_item_id, kind, body, status
  `proposed|approved|rejected|superseded`, refinement_prompt,
  session_id, created_at)
- Create: `backend/app/orchestrator/proposals.py`
- Test: `backend/tests/test_proposals.py`

**Interfaces:**
- Produces: `Proposal` domain model + store methods; a refinement
  creates a new row and marks the old one `superseded` so the full
  history is auditable.

- [ ] Round-trip + supersede-chain tests.
- [ ] Commit.

### Task 2: Description proposal step + refine loop

**Files:**
- Modify: `backend/app/orchestrator/service.py`
- Create: `backend/app/orchestrator/prompts.py` (describe/plan
  prompt builders; embeds original issue + questionnaire answers)
- Test: `backend/tests/test_describe_step.py`

**Interfaces:**
- Consumes: `StepRunner` (step `"describe"`, Sonnet), answers from
  M-D, `Proposal` (Task 1).
- Produces: on `answers_submitted`/`no_gaps`: generate description
  proposal → `awaiting_description_approval`. On refine: resume
  the same session with the refinement prompt → new proposal row.

- [ ] Faked-runner tests: generate, refine (asserts `--resume` with
      prior session id), reject-final.
- [ ] Commit.

### Task 3: Approval endpoints (both gates)

**Files:**
- Modify: `backend/app/routers/work_items.py`
- Test: `backend/tests/test_approval_api.py`

**Interfaces:**
- Produces:
  `POST /api/work-items/{id}/description/approve`,
  `POST /api/work-items/{id}/description/reject`
  (optional body `{"refinement_prompt": "..."}` — with prompt →
  regenerate; without → terminal `rejected`), and the identical
  pair under `/plan/…`. Removes the last of M-B's temporary
  `advance` scaffolding.

- [ ] All six outcomes tested (approve/reject/refine × two gates).
- [ ] Commit.

### Task 4: Write-back + plan step + implementation trigger

**Files:**
- Modify: `backend/app/orchestrator/service.py`
- Test: `backend/tests/test_gate_side_effects.py`

**Interfaces:**
- Consumes: `GitHubSource.update_description` (M-C), StepRunner
  step `"plan"` (Sonnet).
- Produces: description approval → issue body updated on GitHub
  (with an HTML comment marker noting kestrel refined it) →
  `planning` → plan proposal → `awaiting_plan_approval`; plan
  approval → `implementing` event handed to M-F's runner (until
  M-F lands: records the trigger and stops — the seam is the
  state-machine event, nothing else).

- [ ] Mocked-GitHub write-back test incl. API-failure path
      (→ `failed`, error persisted).
- [ ] Commit.

### Task 5: Frontend proposal review UI

**Files:**
- Create: `frontend/src/components/ProposalReview.vue`
- Modify: `frontend/src/api/index.ts`, work-item composable
- Test: `frontend/tests/components/ProposalReview.test.ts`

**Interfaces:**
- Produces: renders proposal markdown (description or plan),
  three actions: **Approve**, **Reject**, **Request changes**
  (textarea for the refinement prompt, disabled-empty). Shows
  supersede history collapsed.

- [ ] Component tests for all three actions and both kinds.
- [ ] Commit.

## Verification

- Suites green.
- Manual E2E on the sandbox repo: vague issue → interview → approve
  the proposed description → **verify the real GitHub issue body
  changed** → refine the plan once with a prompt → approve → state
  reaches `implementing` trigger. Confirm describe/plan sessions
  recorded `sonnet`.
- Tick M-E in `kestrel-roadmap.md`.

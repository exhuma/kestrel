# Kestrel Roadmap — Milestone Tracker

Living document. Tick a milestone when its plan is fully executed,
verified, and merged. Spec: `../specs/2026-07-01-kestrel-design.md`.

## How to use this tracker

1. Pick the first unchecked milestone below.
2. Open its plan. If it is marked **DRAFT (task-level)**, first expand
   it to step-level detail (superpowers:writing-plans) against the
   then-current code — earlier milestones will have changed the shapes
   it builds on.
3. Execute it (superpowers:subagent-driven-development or
   superpowers:executing-plans), ticking task checkboxes in the plan.
4. Verify per the plan's verification section, tick the milestone here,
   commit.

## Milestones

- [x] **M-A · Foundation & rename** —
  [plan](2026-07-01-kestrel-m-a-foundation.md) — **DONE 2026-07-01**
  Rename to kestrel, SQLite persistence behind the registry, model
  policy module. No new behaviour.
- [x] **M-B · Durable workflow runs** —
  [plan](2026-07-02-kestrel-m-b-durable-workflows.md) —
  **DONE 2026-07-02** (reconciled against master's workflow v1;
  supersedes the pre-merge orchestrator draft)
  Workflow runs persisted at every transition; gate-parked runs
  survive restarts and resume their claude session; model policy
  wired into every step.
- [ ] **M-C · GitHub ingestion & repo ops** —
  [plan](2026-07-01-kestrel-m-c-github.md) — DRAFT (task-level)
  Webhook + HMAC + dedup + poll reconciliation, GitHubSource,
  worktree workspace manager.
- [ ] **M-D · Interview subsystem** —
  [plan](2026-07-01-kestrel-m-d-interview.md) — DRAFT (task-level)
  Questionnaire schema/validation, gap-analysis output contract,
  web-UI form renderer, answer capture.
- [x] **M-E · Reject-with-refinement gates** —
  [plan](2026-07-02-kestrel-m-e-refinement-gates.md) —
  **DONE 2026-07-02** (reconciled against master's workflow v1;
  supersedes the pre-merge proposal-gates draft — no separate
  `proposal` table, since the step's deliverable + session
  history already give full auditability)
  Rejecting a gate with a refinement prompt resumes the phase's
  claude session with the feedback and regenerates the
  deliverable at the same gate; a bare reject stays terminal.
  Applies to the refine, plan, and implement gates.
- [ ] **M-F · Autonomous implementation & PR** —
  [plan](2026-07-01-kestrel-m-f-implementation.md) — DRAFT (task-level)
  Implementation in a worktree, blocker pause → clarify → resume,
  commit/push, (draft) PR, Notifier protocol.
- [ ] **M-G · UI overhaul & ergonomics** —
  [plan](2026-07-01-kestrel-m-g-ui.md) — DRAFT (task-level)
  Human-friendly event rendering with raw-JSON access, dashboard/
  timeline, notification center + in-app Notifier back-end.
- [ ] **M-H · Deferred / optional** —
  [plan](2026-07-01-kestrel-m-h-deferred.md) — BACKLOG
  Access gate, extra Notifier back-ends, Planka/Zammad sources.
  Unordered; pick items on demand.

## Status log

| Date | Note |
| --- | --- |
| 2026-07-01 | Spec approved; all milestone plans written. M-A ready. |
| 2026-07-01 | M-A executed and verified (25 backend + 5 frontend tests; real-session restart E2E passed). Next: M-B. |
| 2026-07-02 | Plans reconciled with master's workflow v1 (GitHubClient/GitService/WorkflowService already exist). M-B rescoped to durable workflow runs, executed and verified. next-steps.md persistence gap closed. Next: M-E refine loops or M-D questionnaires. |
| 2026-07-02 | M-E executed and verified (92 backend + 10 frontend tests; real-run E2E on exhuma/kestrel#2 — reject-with-feedback resumed the original refine session and incorporated the feedback; bare reject confirmed terminal). Next: M-D questionnaires or M-C webhooks. |

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

- [ ] **M-A · Foundation & rename** —
  [plan](2026-07-01-kestrel-m-a-foundation.md) — **READY (step-level)**
  Rename to kestrel, SQLite persistence behind the registry, model
  policy module. No new behaviour.
- [ ] **M-B · Orchestrator state machine** —
  [plan](2026-07-01-kestrel-m-b-orchestrator.md) — DRAFT (task-level)
  Durable work items, the lifecycle state machine, StepRunner. Driven
  with stubbed inputs; no GitHub yet.
- [ ] **M-C · GitHub ingestion & repo ops** —
  [plan](2026-07-01-kestrel-m-c-github.md) — DRAFT (task-level)
  Webhook + HMAC + dedup + poll reconciliation, GitHubSource,
  worktree workspace manager.
- [ ] **M-D · Interview subsystem** —
  [plan](2026-07-01-kestrel-m-d-interview.md) — DRAFT (task-level)
  Questionnaire schema/validation, gap-analysis output contract,
  web-UI form renderer, answer capture.
- [ ] **M-E · Proposal & approval gates** —
  [plan](2026-07-01-kestrel-m-e-gates.md) — DRAFT (task-level)
  Description + plan proposals, approve/reject/refine loops, write
  approved description back to the issue.
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

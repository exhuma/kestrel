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
- [x] **M-D · Structured questionnaires** —
  [plan](2026-07-02-kestrel-m-d-questionnaires.md) —
  **DONE 2026-07-02** (reconciled against master's workflow v1;
  supersedes the pre-merge `work_item` interview draft — no
  `questionnaire`/`answer` tables, no separate gap-analysis step,
  no JSON-Schema prompt dump, no `@vue/test-utils`; see the plan's
  header for the full deviation rationale)
  The refine agent asks clarifying questions as a typed
  `<QUESTIONS>` JSON block; the UI renders real form controls
  (radio/checkbox/textarea) with "why" hints instead of one
  free-text box. Malformed or absent questionnaires fall back to
  the original free-text reply with zero regression risk.
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
- [x] **M-F · Implementation blockers & delivery** —
  [plan](2026-07-02-kestrel-m-f-implementation-blockers.md) —
  **DONE 2026-07-02** (reconciled against master's workflow v1;
  supersedes the pre-merge `WorkspaceManager`/`KESTREL_BLOCKER`
  draft — reuses the exact `<QUESTIONS>` contract from M-D, no
  round cap/`blocked` outcome, no `Notifier` protocol yet since
  M-G's notification center is its only consumer; see the plan's
  header for the full deviation rationale)
  If the implementation agent hits a genuine blocker, it pauses
  with a structured question (reusing `_refine`'s exact
  mechanism) and resumes the *same* session once answered — an
  empty `git diff` after a run is the deterministic signal that
  distinguishes "blocked" from "done", since a real diff has no
  tag to check. `reply`/`submit_answers` now route to whichever
  step is awaiting input, not just refine. Delivery (commit,
  push, draft PR) was already built; unchanged.
- [x] **M-G · Human-friendly events & notifications** —
  [plan](2026-07-03-kestrel-m-g-ui-ergonomics.md) —
  **DONE 2026-07-03** (reconciled against master's workflow v1;
  supersedes the pre-merge `work_item` dashboard/timeline draft —
  **scope explicitly narrowed by user decision** to event
  rendering + the Notifier; the dashboard/timeline rework was
  dropped entirely; polling replaces SSE for notifications; see
  the plan's header for the full deviation rationale)
  `WorkflowPanel`'s raw JSON telemetry dump is now typed,
  human-readable event cards (chat bubbles, collapsed tool calls,
  thinking chips, result banners) with a raw-JSON toggle on every
  card. A `Notifier` protocol + in-app back-end fires whenever a
  run needs attention or finishes; the UI shows a live-polled bell
  badge that navigates straight to the relevant run on click.
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
| 2026-07-02 | M-D executed and verified (107 backend + 17 frontend tests; real-run E2E on exhuma/kestrel#2 through the actual browser — a genuine `<QUESTIONS>` block rendered as a radio-button form with a "why" hint, answer submission resumed the session and correctly shaped the refined issue; a separate run also proved the free-text fallback when the model didn't comply). Next: M-C webhooks or M-F autonomous implementation. |
| 2026-07-02 | M-F executed and verified (112 backend tests; a real, unprompted-by-fixture mid-implementation blocker fired on the first live attempt — same `QuestionnaireForm` UI rendered it with zero frontend changes, answering it resumed the exact same claude session that produced the plan, and the run completed end-to-end to a real draft PR, exhuma/kestrel#7, left open for human review). Restart-recovery of an implement blocker relies on unit coverage plus architectural identity with M-B's already-live-restart-verified refine recovery, rather than a repeated live restart. Next: M-C webhooks or M-G UI overhaul. |
| 2026-07-03 | M-G scoped down to event rendering + Notifier (dashboard/timeline dropped) by explicit user decision. Executed and verified (124 backend + 33 frontend tests; real-run E2E — a live workflow's raw telemetry rendered as typed cards including a graceful unknown-shape fallback for one assistant event, a real notification fired on the awaiting_plan_approval transition, the bell badge updated without a reload, and clicking it navigated to and marked-read the correct run). Next: M-C webhooks or M-H backlog items. |

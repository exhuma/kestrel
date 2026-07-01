# M-G · UI Overhaul & Ergonomics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.
> When building the visual pieces, additionally apply
> frontend-design:frontend-design for the aesthetic direction.

> **STATUS: DRAFT (task-level).** Depends on M-B..M-F (work items,
> questionnaires, proposals, notifications all exist). Before
> execution, expand each task to step-level TDD detail
> (superpowers:writing-plans) against the then-current codebase.

**Goal:** Replace the raw-JSON event firehose with a human-friendly,
typed rendering (raw always accessible), add a per-work-item
dashboard/timeline with surfaced pending actions, and a notification
center over the M-F Notifier rows.

**Architecture:** Pure frontend + small read-API additions. Event
rendering is a deterministic mapper from stream-json event shapes
(the spike documented them: `system`, `assistant`, `user`,
`result`, `rate_limit_event`) to display components; unknown shapes
fall back to the raw view, so new CLI event types can never break
the page.

**Tech Stack:** Vue 3 + Vuetify 4, vitest; SSE (existing endpoint).

## Global Constraints

Same frontend rules as before (no new state libs, fetch-only via
`src/api`). Keep the raw event JSON one click away everywhere.

---

### Task 1: Typed event mapper

**Files:**
- Create: `frontend/src/lib/eventView.ts`
- Test: `frontend/tests/lib/eventView.test.ts`

**Interfaces:**
- Produces: `toViewModel(e: SessionEvent) -> EventVM` with
  discriminated kinds: `chat` (assistant text), `tool_call`
  (name + input summary + result), `thinking`, `system`
  (subtype), `result` (cost/duration/summary), `unknown`
  (raw passthrough). Pure function — fully unit-testable with
  recorded spike fixtures.

- [ ] Fixtures from a real session drive the mapper tests,
      including an unrecognised event type → `unknown`.
- [ ] Commit.

### Task 2: Event display components

**Files:**
- Create: `frontend/src/components/EventStream.vue`
- Create: `frontend/src/components/EventCard.vue`
- Modify: `frontend/src/components/SessionPanel.vue` (use them)
- Test: `frontend/tests/components/EventStream.test.ts`

**Interfaces:**
- Consumes: Task 1 view models.
- Produces: chat bubbles for assistant text; collapsible cards for
  tool calls (collapsed by default); thinking collapsed under a
  subtle chip; result as a summary banner; a per-event "{ }"
  toggle and a global "Raw JSON" drawer showing the untouched
  payload (requirement: raw stays accessible).

- [ ] Rendering tests per kind; raw drawer contains the exact
      original JSON.
- [ ] Commit.

### Task 3: Work-item dashboard & timeline

**Files:**
- Create: `frontend/src/components/WorkItemList.vue`
- Create: `frontend/src/components/WorkItemDetail.vue`
- Modify: `frontend/src/App.vue` (navigation: work items become
  the primary view; raw sessions demoted to a secondary tab)
- Modify: backend `GET /api/work-items/{id}` to include a
  `timeline` array (state changes + proposals + questionnaires +
  sessions with timestamps) if M-B/M-E didn't already expose it
- Test: `frontend/tests/components/WorkItemDetail.test.ts`

**Interfaces:**
- Produces: list view (state chips, pending-action badge); detail
  view = vertical timeline (Vuetify timeline) embedding the M-D
  questionnaire form, M-E proposal review, and Task 2 event stream
  at the right steps.

- [ ] Timeline renders a fixture item covering every lifecycle
      stage; pending action (questionnaire/approval) visually
      prominent at the top.
- [ ] Commit.

### Task 4: Notification center

**Files:**
- Create: `frontend/src/components/NotificationCenter.vue`
- Modify: backend: `GET /api/notifications`,
  `POST /api/notifications/{id}/read`, and inclusion of
  notification events on an SSE channel (extend the existing SSE
  pattern)
- Modify: `frontend/src/App.vue` (bell icon + badge in app bar)
- Test: both sides

**Interfaces:**
- Consumes: M-F `notification` rows / `InAppNotifier`.
- Produces: live-updating bell badge; clicking a notification
  navigates to the work item's pending action; mark-as-read.

- [ ] Unread count updates live over SSE; read-state persists.
- [ ] Commit.

## Verification

- Suites green.
- Manual: run a full lifecycle; the default view must let you
  follow everything without reading raw JSON once — then verify
  every displayed event still exposes its raw JSON via the toggle.
  Bell badge fires when the interview and the two gates become
  pending, and when the PR opens.
- Tick M-G in `kestrel-roadmap.md`.

# M-G · Human-Friendly Events & Notifications — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

> Supersedes the task-level draft `2026-07-01-kestrel-m-g-ui.md`
> (written pre-merge, assuming a `work_item` dashboard/timeline
> concept that doesn't exist). Reconciled against master, and
> **scoped down by explicit user decision**: this round covers
> only human-friendly event rendering and the `Notifier` protocol
> + in-app back-end. The dashboard/timeline rework is dropped
> entirely — there is no separate history table (M-B stores only
> current step state), and building one to synthesize a "timeline"
> was judged bigger than this round's value.
>
> **Deviations from the old draft, and why:**
> - **No Vuetify components.** Confirmed zero `<v-…>` usage
>   anywhere despite the library being registered; continues the
>   hand-rolled CSS + `theme.css` tokens pattern from
>   `WorkflowPanel.vue`/`QuestionnaireForm.vue`.
> - **`SessionPanel.vue` is left untouched.** It already renders
>   events reasonably (its own `preview()`/`tone()`/`glyph()`
>   functions) — the actual raw-JSON-dump problem lives only in
>   `WorkflowPanel.vue`'s "Live telemetry" block. Consolidating
>   `SessionPanel` onto the new shared mapper would be a nice DRY
>   win but is unrelated scope creep for this round; the new
>   `frontend/src/lib/eventView.ts` module is available for it to
>   adopt later.
> - **Per-event raw-JSON toggle only, no global drawer.** Simpler,
>   and satisfies "raw JSON stays accessible" without a second UI
>   surface.
> - **Notifications are polled every 5s, not pushed over SSE.** A
>   bell badge doesn't need push latency; polling avoids a second
>   always-on `EventSource` alongside the per-session event feed
>   that already exists.
> - **One centralized notify hook, not three hand-placed calls.**
>   Every one of `WorkflowService`'s ~20 internal
>   `self.workflows.save(run)` call sites becomes `self._save(run)`,
>   which persists *and* notifies whenever the new status is
>   attention-worthy. Filtering happens once, inside the notifier —
>   call sites for transient states (`"refining"`, `"cloning"`, …)
>   need no per-site judgment call, so none can be missed.
> - **`rejected` does not notify.** The human caused it themselves
>   by calling `reject()` with no feedback; notifying them about
>   their own action is noise. Only `awaiting_*` (needs attention),
>   `done` (PR ready), and `failed` notify — the spec's original
>   three trigger kinds, exactly.

**Goal:** Replace `WorkflowPanel.vue`'s raw `JSON.stringify(e.raw)`
telemetry dump with typed, human-readable event cards (raw JSON
still one click away), and add a `Notifier` protocol with an
in-app back-end so the UI surfaces a bell badge whenever a run
needs attention or finishes.

**Architecture:** `frontend/src/lib/eventView.ts` is a pure
classifier (`toViewModel`) turning a `SessionEvent` into a typed
`EventVM`; `EventCard.vue` renders one, with a uniform expand
toggle for the raw payload. Backend: `app/notifications.py` holds
the `Notifier` protocol, deterministic message templates, and
`InAppNotifier`; `app/persistence/notification_store.py` persists
rows (write-through, matching `WorkflowStore`'s established
pattern) behind a new `notification` table (migration 0003).
`WorkflowService._save()` wraps every existing
`self.workflows.save(run)` call, checkpointing and notifying in
one place. Frontend polls `GET /api/notifications` every 5s via a
`useNotifications()` singleton composable.

**Tech Stack:** unchanged — Vue 3 `<script setup lang="ts">` +
hand-rolled CSS, vitest; FastAPI, SQLAlchemy/Alembic, pytest.

## Global Constraints

Same as prior milestones: 80-char lines; `uv`/`npm` only; Sphinx
docstrings + full typing; tests' docstrings start with "Ensure …";
no `@vue/test-utils` / component-mount tests (none exist in this
project — `.vue` files are verified by typecheck + manual E2E,
matching `QuestionnaireForm.vue`'s precedent); backend commands
from `backend/`, frontend from `frontend/`.

---

### Task 1: Typed event classifier (`eventView.ts`)

**Files:**
- Create: `frontend/src/lib/eventView.ts`
- Test: `frontend/tests/lib/eventView.test.ts`

**Interfaces:**
- Produces: `EventViewKind` — a discriminated union:
  - `{ kind: 'chat'; role: 'assistant' | 'user'; text: string }`
  - `{ kind: 'tool_call'; name: string; input: string; preface?: string }`
  - `{ kind: 'tool_result'; content: string; isError: boolean }`
  - `{ kind: 'thinking'; tokens: number }`
  - `{ kind: 'system'; subtype: string; summary: string }`
  - `{ kind: 'rate_limit'; status: string }`
  - `{ kind: 'result'; success: boolean; durationMs: number | null; summary: string | null }`
  - `{ kind: 'unknown' }`
  - `EventVM { raw: Record<string, unknown>; type: string; view: EventViewKind }`
  - `toViewModel(e: SessionEvent) -> EventVM` — pure, never throws.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/lib/eventView.test.ts`. Every fixture below
is a **real event** captured live from this project's own claude
sessions during earlier milestone verification (not fabricated):

```typescript
import { describe, it, expect } from 'vitest'
import { toViewModel } from '../../src/lib/eventView'
import type { SessionEvent } from '../../src/types/sessions'

function ev(raw: Record<string, unknown>): SessionEvent {
  return {
    type: raw.type as string,
    session_id: (raw.session_id as string) ?? null,
    raw,
  }
}

describe('toViewModel', () => {
  it('classifies an assistant text message as chat', () => {
    const vm = toViewModel(ev({
      type: 'assistant',
      message: {
        model: 'claude-sonnet-5', role: 'assistant',
        content: [{
          type: 'text',
          text: 'Let me check the existing test conventions.',
        }],
      },
    }))
    expect(vm.view).toEqual({
      kind: 'chat', role: 'assistant',
      text: 'Let me check the existing test conventions.',
    })
  })

  it('classifies an assistant tool_use message as tool_call', () => {
    const vm = toViewModel(ev({
      type: 'assistant',
      message: {
        model: 'claude-sonnet-5', role: 'assistant',
        content: [{
          type: 'tool_use',
          id: 'toolu_01DVZSbprR4Ay1eb9PSREox5',
          name: 'Read',
          input: { file_path: '/home/exhuma/work/agent-dispatcher/backend/app/main.py' },
        }],
      },
    }))
    expect(vm.view).toEqual({
      kind: 'tool_call', name: 'Read',
      input: '/home/exhuma/work/agent-dispatcher/backend/app/main.py',
      preface: undefined,
    })
  })

  it('keeps preceding text as a preface on a tool_call', () => {
    const vm = toViewModel(ev({
      type: 'assistant',
      message: {
        role: 'assistant',
        content: [
          { type: 'text', text: 'Checking the file first.' },
          { type: 'tool_use', name: 'Read', input: { path: 'x.py' } },
        ],
      },
    }))
    expect(vm.view).toEqual({
      kind: 'tool_call', name: 'Read', input: 'x.py',
      preface: 'Checking the file first.',
    })
  })

  it('classifies a user tool_result message', () => {
    const vm = toViewModel(ev({
      type: 'user',
      message: {
        role: 'user',
        content: [{
          type: 'tool_result',
          tool_use_id: 'toolu_01DVZSbprR4Ay1eb9PSREox5',
          content: 'file contents here',
        }],
      },
    }))
    expect(vm.view).toEqual({
      kind: 'tool_result', content: 'file contents here', isError: false,
    })
  })

  it('classifies a plain user text message as chat', () => {
    const vm = toViewModel(ev({
      type: 'user',
      message: { role: 'user', content: [{ type: 'text', text: 'Blue, please' }] },
    }))
    expect(vm.view).toEqual({ kind: 'chat', role: 'user', text: 'Blue, please' })
  })

  it('classifies system thinking_tokens as thinking', () => {
    const vm = toViewModel(ev({
      type: 'system', subtype: 'thinking_tokens',
      estimated_tokens: 150, estimated_tokens_delta: 100,
      uuid: '14181bf3-4bc7-45f1-b8b8-73cd55e67e5f',
    }))
    expect(vm.view).toEqual({ kind: 'thinking', tokens: 150 })
  })

  it('classifies other system subtypes generically', () => {
    const vm = toViewModel(ev({
      type: 'system', subtype: 'hook_started',
      hook_id: 'e3ab1542-a99e-4c17-9f1c-739b3627e937',
      hook_name: 'SessionStart:startup',
    }))
    expect(vm.view).toEqual({
      kind: 'system', subtype: 'hook_started',
      summary: 'SessionStart:startup',
    })
  })

  it('classifies rate_limit_event', () => {
    const vm = toViewModel(ev({
      type: 'rate_limit_event',
      rate_limit_info: {
        status: 'allowed_warning', resetsAt: 1783027200,
        rateLimitType: 'five_hour', utilization: 0.9,
      },
    }))
    expect(vm.view).toEqual({ kind: 'rate_limit', status: 'allowed_warning' })
  })

  it('classifies a successful result', () => {
    const vm = toViewModel(ev({
      type: 'result', subtype: 'success', is_error: false,
      duration_ms: 19164, result: 'Implemented using config.yaml',
    }))
    expect(vm.view).toEqual({
      kind: 'result', success: true, durationMs: 19164,
      summary: 'Implemented using config.yaml',
    })
  })

  it('classifies a failed result', () => {
    const vm = toViewModel(ev({
      type: 'result', subtype: 'error_max_turns', is_error: true,
      duration_ms: 500,
    }))
    expect(vm.view).toEqual({
      kind: 'result', success: false, durationMs: 500, summary: null,
    })
  })

  it('falls back to unknown for an unrecognised type', () => {
    const vm = toViewModel(ev({ type: 'totally_new_event_type', foo: 'bar' }))
    expect(vm.view).toEqual({ kind: 'unknown' })
    expect(vm.raw).toEqual({ type: 'totally_new_event_type', foo: 'bar' })
  })

  it('falls back to unknown for a malformed assistant message', () => {
    const vm = toViewModel(ev({ type: 'assistant', message: {} }))
    expect(vm.view).toEqual({ kind: 'unknown' })
  })

  it('always carries the original type and raw payload', () => {
    const raw = { type: 'result', subtype: 'success', is_error: false }
    const vm = toViewModel(ev(raw))
    expect(vm.type).toBe('result')
    expect(vm.raw).toEqual(raw)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test`
Expected: FAIL with a module-not-found error for
`../../src/lib/eventView`.

- [ ] **Step 3: Implement**

Create `frontend/src/lib/eventView.ts`:

```typescript
import type { SessionEvent } from '../types/sessions'

export type EventViewKind =
  | { kind: 'chat'; role: 'assistant' | 'user'; text: string }
  | { kind: 'tool_call'; name: string; input: string; preface?: string }
  | { kind: 'tool_result'; content: string; isError: boolean }
  | { kind: 'thinking'; tokens: number }
  | { kind: 'system'; subtype: string; summary: string }
  | { kind: 'rate_limit'; status: string }
  | {
      kind: 'result'
      success: boolean
      durationMs: number | null
      summary: string | null
    }
  | { kind: 'unknown' }

export interface EventVM {
  raw: Record<string, unknown>
  type: string
  view: EventViewKind
}

interface ContentBlock {
  type?: string
  text?: string
  name?: string
  input?: Record<string, unknown>
  content?: unknown
  is_error?: boolean
}

function messageContent(raw: Record<string, unknown>): ContentBlock[] | null {
  const message = raw.message as { content?: unknown } | undefined
  const content = message?.content
  return Array.isArray(content) ? (content as ContentBlock[]) : null
}

function toolInputSummary(input: Record<string, unknown> | undefined): string {
  if (!input) return ''
  const arg = input.file_path ?? input.path ?? input.command
  return typeof arg === 'string' ? arg : JSON.stringify(input)
}

function classifyAssistant(raw: Record<string, unknown>): EventViewKind {
  const content = messageContent(raw)
  if (!content) return { kind: 'unknown' }
  const toolUse = content.find((c) => c.type === 'tool_use')
  const texts = content
    .filter((c) => c.type === 'text' && typeof c.text === 'string')
    .map((c) => c.text as string)
  if (toolUse && typeof toolUse.name === 'string') {
    return {
      kind: 'tool_call',
      name: toolUse.name,
      input: toolInputSummary(toolUse.input),
      preface: texts.length ? texts.join(' ') : undefined,
    }
  }
  if (texts.length) return { kind: 'chat', role: 'assistant', text: texts.join('\n') }
  return { kind: 'unknown' }
}

function classifyUser(raw: Record<string, unknown>): EventViewKind {
  const content = messageContent(raw)
  if (!content) return { kind: 'unknown' }
  const toolResult = content.find((c) => c.type === 'tool_result')
  if (toolResult) {
    return {
      kind: 'tool_result',
      content:
        typeof toolResult.content === 'string'
          ? toolResult.content
          : JSON.stringify(toolResult.content),
      isError: !!toolResult.is_error,
    }
  }
  const texts = content
    .filter((c) => c.type === 'text' && typeof c.text === 'string')
    .map((c) => c.text as string)
  if (texts.length) return { kind: 'chat', role: 'user', text: texts.join('\n') }
  return { kind: 'unknown' }
}

function classifySystem(raw: Record<string, unknown>): EventViewKind {
  const subtype = typeof raw.subtype === 'string' ? raw.subtype : 'unknown'
  if (subtype === 'thinking_tokens') {
    const tokens = raw.estimated_tokens
    return { kind: 'thinking', tokens: typeof tokens === 'number' ? tokens : 0 }
  }
  const summary =
    (typeof raw.hook_name === 'string' && raw.hook_name) ||
    (typeof raw.status_category === 'string' && raw.status_category) ||
    subtype
  return { kind: 'system', subtype, summary }
}

function classifyResult(raw: Record<string, unknown>): EventViewKind {
  const durationMs = typeof raw.duration_ms === 'number' ? raw.duration_ms : null
  const summary = typeof raw.result === 'string' ? raw.result : null
  return { kind: 'result', success: !raw.is_error, durationMs, summary }
}

function classifyRateLimit(raw: Record<string, unknown>): EventViewKind {
  const info = raw.rate_limit_info as { status?: unknown } | undefined
  const status = typeof info?.status === 'string' ? info.status : 'unknown'
  return { kind: 'rate_limit', status }
}

/** Classify a raw stream-json event into a typed view model. Never throws. */
export function toViewModel(e: SessionEvent): EventVM {
  const raw = e.raw
  let view: EventViewKind
  switch (e.type) {
    case 'assistant':
      view = classifyAssistant(raw)
      break
    case 'user':
      view = classifyUser(raw)
      break
    case 'system':
      view = classifySystem(raw)
      break
    case 'result':
      view = classifyResult(raw)
      break
    case 'rate_limit_event':
      view = classifyRateLimit(raw)
      break
    default:
      view = { kind: 'unknown' }
  }
  return { raw, type: e.type, view }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test` — all pass, including the 13 new `toViewModel`
tests.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(frontend): add typed event classifier for stream-json events"
```

---

### Task 2: EventCard component + wire into WorkflowPanel

**Files:**
- Create: `frontend/src/components/EventCard.vue`
- Modify: `frontend/src/components/WorkflowPanel.vue`

**Interfaces:**
- Consumes: `EventVM`, `toViewModel` (Task 1).
- Produces: `EventCard` prop `{ event: EventVM }`; renders per
  `event.view.kind` with a uniform "{ }" toggle revealing
  `JSON.stringify(event.raw, null, 2)`. No new automated test
  (presentational component; verified by typecheck + manual E2E,
  per this project's established precedent for `.vue` files).

- [ ] **Step 1: Implement the component**

Create `frontend/src/components/EventCard.vue`:

```vue
<script setup lang="ts">
import { ref } from 'vue'
import type { EventVM } from '../lib/eventView'

defineProps<{ event: EventVM }>()
const expanded = ref(false)
</script>

<template>
  <div class="ecard" :class="`ecard--${event.view.kind}`">
    <div class="ecard__row">
      <template v-if="event.view.kind === 'chat'">
        <span class="ecard__role mono">{{ event.view.role }}</span>
        <p class="ecard__text">{{ event.view.text }}</p>
      </template>

      <template v-else-if="event.view.kind === 'tool_call'">
        <details class="ecard__tool">
          <summary>
            <span aria-hidden="true">⚙</span> {{ event.view.name }}
            <span v-if="event.view.input" class="mono ecard__tool-arg">
              · {{ event.view.input }}
            </span>
          </summary>
          <p v-if="event.view.preface" class="ecard__preface">
            {{ event.view.preface }}
          </p>
        </details>
      </template>

      <template v-else-if="event.view.kind === 'tool_result'">
        <span class="ecard__glyph" aria-hidden="true">↳</span>
        <span class="ecard__result-text mono"
          :class="{ 'ecard__result-text--err': event.view.isError }">
          {{ event.view.content.length > 160
            ? `${event.view.content.slice(0, 160)}…`
            : event.view.content }}
        </span>
      </template>

      <template v-else-if="event.view.kind === 'thinking'">
        <span class="chip t-sys mono">thinking… ~{{ event.view.tokens }} tok</span>
      </template>

      <template v-else-if="event.view.kind === 'system'">
        <span class="ecard__sys mono">{{ event.view.summary }}</span>
      </template>

      <template v-else-if="event.view.kind === 'rate_limit'">
        <span class="chip t-warn mono">rate limit: {{ event.view.status }}</span>
      </template>

      <template v-else-if="event.view.kind === 'result'">
        <div class="ecard__banner" :class="event.view.success ? 't-ok' : 't-err'">
          <span>{{ event.view.success ? '✓ done' : '✕ failed' }}</span>
          <span v-if="event.view.durationMs" class="mono">
            {{ (event.view.durationMs / 1000).toFixed(1) }}s
          </span>
          <span v-if="event.view.summary" class="ecard__banner-text">
            {{ event.view.summary }}
          </span>
        </div>
      </template>

      <template v-else>
        <span class="ecard__type mono">{{ event.type }}</span>
        <span class="ecard__fallback mono">
          {{ JSON.stringify(event.raw).slice(0, 140) }}
        </span>
      </template>

      <button class="ecard__toggle mono" @click="expanded = !expanded"
        :aria-label="expanded ? 'Hide raw JSON' : 'Show raw JSON'">
        { }
      </button>
    </div>
    <pre v-if="expanded" class="ecard__raw mono">{{
      JSON.stringify(event.raw, null, 2)
    }}</pre>
  </div>
</template>

<style scoped>
.ecard { padding: 6px 0; border-bottom: 1px solid var(--line-soft); font-size: 12.5px; }
.ecard__row { display: flex; align-items: flex-start; gap: 8px; }
.ecard__role { color: var(--text-dim); flex: none; width: 60px; }
.ecard--chat .ecard__text { margin: 0; color: var(--text-hi); white-space: pre-wrap; flex: 1; }
.ecard__tool { flex: 1; color: var(--text-mid); }
.ecard__tool summary { cursor: pointer; color: var(--warn); }
.ecard__tool-arg { color: var(--text-dim); }
.ecard__preface { margin: 4px 0 0; color: var(--text-mid); }
.ecard__glyph { color: var(--text-dim); flex: none; }
.ecard__result-text { color: var(--text-mid); flex: 1; }
.ecard__result-text--err { color: var(--err); }
.ecard__sys { color: var(--text-dim); flex: 1; }
.ecard__type { color: var(--signal); flex: none; }
.ecard__fallback { color: var(--text-mid); flex: 1; word-break: break-word; }
.ecard__banner {
  --c: var(--ok); display: flex; align-items: center; gap: 10px;
  padding: 6px 10px; border-radius: var(--r-md);
  border: 1px solid color-mix(in srgb, var(--c) 40%, var(--line));
  background: color-mix(in srgb, var(--c) 10%, transparent);
  color: var(--c); flex: 1;
}
.ecard__banner.t-err { --c: var(--err); }
.ecard__banner-text { color: var(--text-hi); }
.ecard__toggle {
  flex: none; background: none; border: 1px solid var(--line); color: var(--text-dim);
  border-radius: var(--r-sm); font-size: 10.5px; padding: 1px 6px; cursor: pointer;
}
.ecard__toggle:hover { color: var(--text-hi); border-color: var(--idle); }
.ecard__raw {
  margin: 6px 0 0; padding: 8px 10px; background: var(--ink-750);
  border: 1px solid var(--line); border-radius: var(--r-md);
  color: var(--text-mid); font-size: 11.5px; white-space: pre-wrap;
  word-break: break-word;
}
.chip {
  --c: var(--idle); display: inline-flex; align-items: center; gap: 6px;
  padding: 2px 9px; border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--c) 40%, var(--line));
  background: color-mix(in srgb, var(--c) 12%, transparent);
  font-size: 11px; color: var(--c);
}
.chip.t-warn { --c: var(--warn); }
.chip.t-sys { --c: var(--idle); }
</style>
```

- [ ] **Step 2: Wire into WorkflowPanel.vue**

`frontend/src/components/WorkflowPanel.vue` — add the import:

```typescript
import EventCard from './EventCard.vue'
import { toViewModel } from '../lib/eventView'
```

(add alongside the existing `QuestionnaireForm`/`parseQuestionnaire`
imports)

Replace the raw telemetry block:

```html
        <div class="feed">
          <div class="eyebrow">Live telemetry</div>
          <div v-for="(e, i) in events" :key="i" class="ev-line mono">
            <span class="ev-line__type">{{ e.type }}</span>
            {{ JSON.stringify(e.raw).slice(0, 140) }}
          </div>
        </div>
```

with:

```html
        <div class="feed">
          <div class="eyebrow">Live telemetry</div>
          <EventCard v-for="(e, i) in events" :key="i" :event="toViewModel(e)" />
        </div>
```

The now-unused `.ev-line`/`.ev-line__type` scoped styles can stay
(harmless dead CSS) or be deleted; delete them for cleanliness —
remove these two rules from the `<style scoped>` block:

```css
.ev-line { font-size: 12px; color: var(--text-mid); }
.ev-line__type { color: var(--signal); margin-right: 8px; }
```

- [ ] **Step 3: Run tests + typecheck**

Run: `npm test` and `npx vue-tsc -b`
Expected: all pass (unchanged test count from Task 1), no type
errors.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(frontend): render workflow telemetry as human-friendly event cards"
```

---

### Task 3: Notifier protocol, message templates, persistence

**Files:**
- Create: `backend/app/notifications.py`
- Create: `backend/app/persistence/notification_store.py`
- Modify: `backend/app/persistence/tables.py`
- Create: `backend/alembic/versions/0003_notification_table.py`
- Test: `backend/tests/test_notifications.py`

**Interfaces:**
- Produces:
  - `NOTIFY_STATUSES`, `render_message(run: WorkflowRun) -> str`,
    `Notification` dataclass, `Notifier` protocol,
    `InAppNotifier(store: NotificationStore)`.
  - `NotificationRow` ORM table; `NotificationStore(factory)` with
    `add(workflow_id, repo, issue_number, status, message)`,
    `list_all() -> list[Notification]` (newest first),
    `mark_read(notification_id)`; singleton `get_notification_store()`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_notifications.py`:

```python
"""Tests for the Notifier protocol, templates, and persistence."""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.models_workflow import WorkflowRun
from app.notifications import InAppNotifier, render_message
from app.persistence.notification_store import NotificationStore


def _migrate(db_path: Path) -> str:
    """Apply all migrations to a fresh SQLite file."""
    url = f"sqlite:///{db_path}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def _store(tmp_path: Path) -> NotificationStore:
    """Build a store on a freshly migrated SQLite file."""
    url = _migrate(tmp_path / "notif.db")
    return NotificationStore(sessionmaker(bind=sa.create_engine(url)))


def _run(status: str) -> WorkflowRun:
    return WorkflowRun(id="wf-1", repo="o/r", issue_number=5, status=status)


def test_migrations_create_notification_table(tmp_path: Path) -> None:
    """Ensure migrations create the notification table."""
    url = _migrate(tmp_path / "t.db")
    names = set(sa.inspect(sa.create_engine(url)).get_table_names())
    assert "notification" in names


def test_render_message_for_known_statuses() -> None:
    """Ensure known statuses render a specific, repo-scoped message."""
    msg = render_message(_run("awaiting_refine_approval"))
    assert "o/r#5" in msg
    assert "review" in msg.lower()


def test_render_message_falls_back_for_unknown_status() -> None:
    """Ensure an unrecognised status still renders something useful."""
    msg = render_message(_run("some_future_status"))
    assert "o/r#5" in msg


def test_in_app_notifier_records_awaiting_status(tmp_path: Path) -> None:
    """Ensure an awaiting_* status is recorded."""
    store = _store(tmp_path)
    notifier = InAppNotifier(store)
    notifier.notify(_run("awaiting_plan_approval"))
    items = store.list_all()
    assert len(items) == 1
    assert items[0].workflow_id == "wf-1"
    assert items[0].repo == "o/r"
    assert items[0].issue_number == 5
    assert items[0].status == "awaiting_plan_approval"
    assert items[0].read is False


def test_in_app_notifier_records_done_and_failed(tmp_path: Path) -> None:
    """Ensure done and failed statuses are recorded."""
    store = _store(tmp_path)
    notifier = InAppNotifier(store)
    notifier.notify(_run("done"))
    notifier.notify(_run("failed"))
    assert len(store.list_all()) == 2


def test_in_app_notifier_ignores_transient_and_rejected(
    tmp_path: Path,
) -> None:
    """Ensure transient and rejected statuses are not recorded."""
    store = _store(tmp_path)
    notifier = InAppNotifier(store)
    for status in ("pending", "cloning", "refining", "rejected"):
        notifier.notify(_run(status))
    assert store.list_all() == []


def test_store_list_all_orders_newest_first(tmp_path: Path) -> None:
    """Ensure notifications list most recent first."""
    store = _store(tmp_path)
    store.add(
        workflow_id="wf-1", repo="o/r", issue_number=1,
        status="done", message="first",
    )
    store.add(
        workflow_id="wf-1", repo="o/r", issue_number=1,
        status="failed", message="second",
    )
    items = store.list_all()
    assert [n.message for n in items] == ["second", "first"]


def test_store_mark_read(tmp_path: Path) -> None:
    """Ensure mark_read flips the read flag for that row only."""
    store = _store(tmp_path)
    store.add(
        workflow_id="wf-1", repo="o/r", issue_number=1,
        status="done", message="x",
    )
    notification_id = store.list_all()[0].id
    store.mark_read(notification_id)
    assert store.list_all()[0].read is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_notifications.py -v`
Expected: FAIL with `ModuleNotFoundError: app.notifications`.

- [ ] **Step 3: Implement**

`backend/app/persistence/tables.py` — add the imports and table:

```python
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
```

(replace the existing `from sqlalchemy import ForeignKey, Text`
import line with the two lines above)

```python
class NotificationRow(Base):
    """One recorded notification for the in-app notification center."""

    __tablename__ = "notification"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_run.id")
    )
    repo: Mapped[str] = mapped_column()
    issue_number: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column()
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
```

(append this class at the end of the file)

Create `backend/alembic/versions/0003_notification_table.py`:

```python
"""Notification table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the notification table."""
    op.create_table(
        "notification",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True
        ),
        sa.Column(
            "workflow_id", sa.String(),
            sa.ForeignKey("workflow_run.id"), nullable=False,
        ),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    """Drop the notification table."""
    op.drop_table("notification")
```

Create `backend/app/notifications.py`:

```python
"""Notifier protocol and in-app back-end for workflow attention
events.

Kept LLM-free and deterministic: messages are rendered from a
fixed per-status template, never generated by a model.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from app.models_workflow import WorkflowRun

if TYPE_CHECKING:
    from app.persistence.notification_store import NotificationStore

#: Statuses that warrant a notification: the human's attention is
#: needed (any "awaiting_*" gate) or the run reached a terminal
#: outcome worth knowing about. "rejected" is excluded — the human
#: caused it themselves by rejecting with no feedback.
NOTIFY_STATUSES = frozenset({"done", "failed"})

_MESSAGES: dict[str, str] = {
    "awaiting_refine_input": (
        "Kestrel needs your input refining {repo}#{issue_number}."
    ),
    "awaiting_refine_approval": (
        "Refined description ready for review: {repo}#{issue_number}."
    ),
    "awaiting_plan_approval": (
        "Implementation plan ready for review: {repo}#{issue_number}."
    ),
    "awaiting_implement_input": (
        "Kestrel needs your input during implementation: "
        "{repo}#{issue_number}."
    ),
    "awaiting_implement_approval": (
        "Implementation ready for review: {repo}#{issue_number}."
    ),
    "done": "PR opened for {repo}#{issue_number}.",
    "failed": "Workflow failed for {repo}#{issue_number}.",
}


def _is_notifiable(status: str) -> bool:
    return status in NOTIFY_STATUSES or status.startswith("awaiting_")


def render_message(run: WorkflowRun) -> str:
    """
    Render the notification text for a run's current status.

    :param run: The run that just transitioned.
    :returns: A human-readable, repo-scoped message.
    """
    template = _MESSAGES.get(
        run.status,
        "Kestrel needs your attention: {repo}#{issue_number}.",
    )
    return template.format(repo=run.repo, issue_number=run.issue_number)


@dataclass
class Notification:
    """A recorded notification for the in-app notification center."""

    id: int
    workflow_id: str
    repo: str
    issue_number: int
    status: str
    message: str
    created_at: datetime
    read: bool


class Notifier(Protocol):
    """Notifies the user about a workflow run needing attention."""

    def notify(self, run: WorkflowRun) -> None:
        """Record a notification for the run's status, if any."""
        ...


class InAppNotifier:
    """Persists a notification row for the in-app notification center."""

    def __init__(self, store: "NotificationStore") -> None:
        self._store = store

    def notify(self, run: WorkflowRun) -> None:
        """
        Record a notification if the run's status warrants one.

        :param run: The run that just transitioned.
        """
        if not _is_notifiable(run.status):
            return
        self._store.add(
            workflow_id=run.id,
            repo=run.repo,
            issue_number=run.issue_number,
            status=run.status,
            message=render_message(run),
        )
```

Create `backend/app/persistence/notification_store.py`:

```python
"""Write-through persistence for in-app notifications."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.notifications import Notification
from app.persistence.db import get_sessionmaker
from app.persistence.tables import NotificationRow


class NotificationStore:
    """Persists notifications for the in-app notification center."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def add(
        self,
        workflow_id: str,
        repo: str,
        issue_number: int,
        status: str,
        message: str,
    ) -> None:
        """
        Record a new notification.

        :param workflow_id: Id of the run that triggered this.
        :param repo: The run's repo, denormalized for display.
        :param issue_number: The run's issue number, denormalized.
        :param status: The run status that triggered this.
        :param message: The rendered notification text.
        """
        with self._factory.begin() as db:
            db.add(
                NotificationRow(
                    workflow_id=workflow_id,
                    repo=repo,
                    issue_number=issue_number,
                    status=status,
                    message=message,
                    created_at=datetime.now(timezone.utc),
                    read=False,
                )
            )

    def list_all(self) -> list[Notification]:
        """
        Return all notifications, most recent first.

        :returns: Every notification, newest first.
        """
        with self._factory() as db:
            stmt = select(NotificationRow).order_by(
                NotificationRow.id.desc()
            )
            return [
                Notification(
                    id=row.id,
                    workflow_id=row.workflow_id,
                    repo=row.repo,
                    issue_number=row.issue_number,
                    status=row.status,
                    message=row.message,
                    created_at=row.created_at,
                    read=row.read,
                )
                for row in db.scalars(stmt)
            ]

    def mark_read(self, notification_id: int) -> None:
        """
        Mark one notification as read.

        :param notification_id: Id of the notification to mark.
        """
        with self._factory.begin() as db:
            row = db.get(NotificationRow, notification_id)
            if row is not None:
                row.read = True


@lru_cache
def get_notification_store() -> NotificationStore:
    """
    Return the process-wide NotificationStore singleton.

    :returns: The cached notification store instance.
    """
    return NotificationStore(get_sessionmaker())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_notifications.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Run the full backend suite and commit**

Run: `uv run pytest -q` — all pass (the new table/module are not
wired into `WorkflowService` yet — that's Task 4).

```bash
git add -A
git commit -m "feat: add Notifier protocol, message templates, and persistence"
```

---

### Task 4: Wire the notifier into WorkflowService

**Files:**
- Modify: `backend/app/services/workflows.py`
- Modify: `backend/tests/test_workflow_service.py`
- Modify: `backend/tests/test_workflow_persistence.py`
- Modify: `backend/tests/test_workflow_recovery.py`

**Interfaces:**
- Consumes: `Notifier`, `InAppNotifier` (Task 3).
- Produces: `WorkflowService.__init__` gains a required `notifier:
  Notifier` parameter; `WorkflowService._save(run)` replaces every
  internal call site that used to say `self.workflows.save(run)` —
  it persists via `self.workflows.save(run)` exactly as before,
  then calls `self.notifier.notify(run)`. `get_workflow_service()`
  constructs `InAppNotifier(get_notification_store())`.
  `_FakeNotifier` (in `test_workflow_service.py`, imported by the
  other two test files per the established fake-sharing pattern)
  records every status it was called with.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_workflow_service.py`, add the fake next to
the other fakes (e.g. after `_FakeGit`):

```python
class _FakeNotifier:
    """Records every status it was notified about."""

    def __init__(self) -> None:
        self.notified: list[str] = []

    def notify(self, run) -> None:
        self.notified.append(run.status)
```

Update the `_service()` helper to construct and expose the fake:

```python
def _service(github, runner, git) -> WorkflowService:
    return WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        runner=runner,
        git=git,
        github=github,
        notifier=_FakeNotifier(),
    )
```

Append these tests:

```python
@pytest.mark.asyncio
async def test_notifier_fires_on_awaiting_and_done() -> None:
    """Ensure attention-worthy statuses reach the notifier."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=["plan", "impl"])
    notifier = _FakeNotifier()
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        runner=runner,
        git=_FakeGit(),
        github=gh,
        notifier=notifier,
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_implement_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert "awaiting_plan_approval" in notifier.notified
    assert "awaiting_implement_approval" in notifier.notified
    assert "done" in notifier.notified
    assert "planning" not in notifier.notified
    assert "implementing" not in notifier.notified


@pytest.mark.asyncio
async def test_notifier_does_not_fire_on_reject() -> None:
    """Ensure a bare reject does not produce a notification."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=["The plan"])
    notifier = _FakeNotifier()
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        runner=runner,
        git=_FakeGit(),
        github=gh,
        notifier=notifier,
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    svc.reject(wid)
    await _wait(lambda: svc.get(wid).status == "rejected")
    assert "rejected" not in notifier.notified
```

In `backend/tests/test_workflow_persistence.py`, update
`_persistent_service()` to pass a notifier:

```python
def _persistent_service(
    store: WorkflowStore, github, runner, git
) -> WorkflowService:
    """Build a WorkflowService on a store-backed registry."""
    reg = WorkflowRegistry(store=store)
    reg.preload(store.load_all())
    return WorkflowService(
        settings=Settings(
            git_base="https://github.com", github_token="t"
        ),
        sessions=runner.sessions,
        workflows=reg,
        runner=runner,
        git=git,
        github=github,
        notifier=_FakeNotifier(),
    )
```

(add `_FakeNotifier` to the existing import from
`tests.test_workflow_service` at the top of the file)

`backend/tests/test_workflow_recovery.py` needs no direct edit —
it imports `_persistent_service` from `test_workflow_persistence`,
so it picks up the fix automatically.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_service.py \
tests/test_workflow_persistence.py tests/test_workflow_recovery.py -v`
Expected: every test that constructs `WorkflowService` directly
FAILS with `TypeError: __init__() missing 1 required keyword-only
argument: 'notifier'` (the two new notifier tests fail the same
way, since they also construct `WorkflowService` directly).

- [ ] **Step 3: Implement**

`backend/app/services/workflows.py` — add the import:

```python
from app.notifications import InAppNotifier, Notifier
from app.persistence.notification_store import get_notification_store
```

(add alongside the existing `from app.questionnaire import ...`
import block)

Update `__init__`:

```python
    def __init__(
        self,
        settings: Settings,
        sessions: SessionRegistry,
        workflows: WorkflowRegistry,
        runner: SessionRunner,
        git: GitService,
        github: GitHubClient,
        notifier: Notifier,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.workflows = workflows
        self.runner = runner
        self.git = git
        self.github = github
        self.notifier = notifier
        self._control: dict[str, _Control] = {}
```

Add `_save` right after `current_session_id`:

```python
    def _save(self, run: WorkflowRun) -> None:
        """
        Persist the run and notify if its new status needs
        attention.

        The single choke point for every state-transition
        checkpoint in this service — replacing
        ``self.workflows.save(run)`` here means no call site can
        forget to notify, and no call site needs to judge for
        itself whether its status is notification-worthy (the
        notifier does that filtering once, centrally).

        :param run: The run to checkpoint.
        """
        self.workflows.save(run)
        self.notifier.notify(run)
```

Now replace **every** remaining `self.workflows.save(run)` call
in the file with `self._save(run)`. There are 21 call sites,
inside `recover()`, `_resume()`, `_drive()`, `_refine()`,
`_plan()`, `_implement()`, and `_deliver()` — every one of them,
with no exceptions (the `_save` method itself is the only place
that still calls the real `self.workflows.save(run)`). The
mechanical way to do this safely:

```bash
python3 - <<'EOF'
from pathlib import Path
p = Path("app/services/workflows.py")
text = p.read_text()
# _save's own body must keep calling the real registry method —
# protect it before the blanket replace, then restore it.
sentinel = "        self.workflows.save(run)\n        self.notifier.notify(run)"
assert text.count(sentinel) == 1
text = text.replace(sentinel, "@@KEEP@@")
assert "self.workflows.save(run)" in text  # other call sites exist
text = text.replace("self.workflows.save(run)", "self._save(run)")
text = text.replace("@@KEEP@@", sentinel)
p.write_text(text)
EOF
```

Run: `grep -c "self._save(run)" app/services/workflows.py` —
expect `21`. Run: `grep -c "self.workflows.save(run)"
app/services/workflows.py` — expect `1` (only inside `_save`
itself).

Update the factory:

```python
@lru_cache
def get_workflow_service() -> WorkflowService:
    """Return the process-wide WorkflowService singleton."""
    settings = get_settings()
    registry = get_registry()
    return WorkflowService(
        settings=settings,
        sessions=registry,
        workflows=get_workflow_registry(),
        runner=SessionRunner(settings, registry),
        git=GitService(settings.github_token),
        github=GitHubClient(settings.github_api_base, settings.github_token),
        notifier=InAppNotifier(get_notification_store()),
    )
```

- [ ] **Step 4: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all pass, including every pre-existing M-B/D/E/F test
(the `_service()`/`_persistent_service()` fixes make them
construct correctly again) and the two new notifier tests.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: wire the notifier into every workflow state transition"
```

---

### Task 5: Notification REST endpoints

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/routers/notifications.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_notifications_router.py`

**Interfaces:**
- Consumes: `NotificationStore`, `Notification` (Task 3).
- Produces: `NotificationOut` schema; `GET /api/notifications`
  (list, newest first); `POST /api/notifications/{id}/read`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_notifications_router.py`, matching the
fake-store style already used in `test_workflows_router.py`:

```python
"""Tests for the notifications router (store mocked)."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.main import create_app
from app.notifications import Notification
from app.persistence.notification_store import get_notification_store


class _FakeStore:
    def __init__(self) -> None:
        self.read_ids: list[int] = []

    def list_all(self) -> list[Notification]:
        return [
            Notification(
                id=2, workflow_id="wf-1", repo="o/r", issue_number=5,
                status="done", message="PR opened for o/r#5.",
                created_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
                read=False,
            ),
            Notification(
                id=1, workflow_id="wf-1", repo="o/r", issue_number=5,
                status="awaiting_plan_approval",
                message="Implementation plan ready for review: o/r#5.",
                created_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
                read=True,
            ),
        ]

    def mark_read(self, notification_id: int) -> None:
        self.read_ids.append(notification_id)


def _client(store):
    app = create_app()
    app.dependency_overrides[get_notification_store] = lambda: store
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_list_notifications_newest_first() -> None:
    """Ensure the list endpoint returns the store's order and fields."""
    async with _client(_FakeStore()) as client:
        resp = await client.get("/api/notifications")
    assert resp.status_code == 200
    body = resp.json()
    assert [n["id"] for n in body] == [2, 1]
    assert body[0]["message"] == "PR opened for o/r#5."
    assert body[0]["read"] is False
    assert body[1]["read"] is True


@pytest.mark.asyncio
async def test_mark_read_calls_store() -> None:
    """Ensure marking a notification read reaches the store."""
    store = _FakeStore()
    async with _client(store) as client:
        resp = await client.post("/api/notifications/1/read")
    assert resp.status_code == 200
    assert store.read_ids == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_notifications_router.py -v`
Expected: FAIL — both routes 404 (they don't exist yet).

- [ ] **Step 3: Implement**

`backend/app/schemas.py` — add the import and schema:

```python
from datetime import datetime
```

(add above the existing `from pydantic import BaseModel` line)

```python
class NotificationOut(BaseModel):
    """One notification for the API."""

    id: int
    workflow_id: str
    repo: str
    issue_number: int
    status: str
    message: str
    created_at: datetime
    read: bool
```

(append at the end of the file)

Create `backend/app/routers/notifications.py`:

```python
"""HTTP routes for the in-app notification center."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.persistence.notification_store import (
    NotificationStore,
    get_notification_store,
)
from app.schemas import NotificationOut

router = APIRouter(prefix="/api/notifications")


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    store: NotificationStore = Depends(get_notification_store),
) -> list[NotificationOut]:
    """List all notifications, most recent first."""
    return [
        NotificationOut(
            id=n.id, workflow_id=n.workflow_id, repo=n.repo,
            issue_number=n.issue_number, status=n.status,
            message=n.message, created_at=n.created_at, read=n.read,
        )
        for n in store.list_all()
    ]


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    store: NotificationStore = Depends(get_notification_store),
) -> dict[str, str]:
    """Mark one notification as read."""
    store.mark_read(notification_id)
    return {"status": "ok"}
```

`backend/app/main.py` — register the router:

```python
    from app.routers import notifications, sessions, workflows

    app.include_router(sessions.router)
    app.include_router(workflows.router)
    app.include_router(notifications.router)
```

(replace the existing three-line import-and-register block at the
bottom of `create_app()`)

- [ ] **Step 4: Run the full backend suite**

Run: `uv run pytest -q` — all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add notification list and mark-read endpoints"
```

---

### Task 6: Frontend notification center

**Files:**
- Create: `frontend/src/types/notifications.ts`
- Create: `frontend/src/composables/useNotifications.ts`
- Create: `frontend/src/components/NotificationCenter.vue`
- Modify: `frontend/src/App.vue`
- Test: `frontend/tests/composables/useNotifications.test.ts`

**Interfaces:**
- Consumes: `GET /api/notifications`,
  `POST /api/notifications/{id}/read` (Task 5).
- Produces: `Notification` type; `useNotifications()` singleton
  composable exposing `items`, `unreadCount`, `refresh`,
  `markRead`, `start` (begins 5s polling), `stop`;
  `NotificationCenter.vue` emits `navigate` when a notification is
  clicked, after selecting that workflow via `useWorkflows().select`.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/composables/useNotifications.test.ts`,
mirroring `useWorkflows.test.ts`'s fake-timer poll test:

```typescript
import { describe, it, expect, vi, afterEach } from 'vitest'
import { useNotifications } from '../../src/composables/useNotifications'

afterEach(() => {
  useNotifications().stop()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

const sample = [
  {
    id: 2, workflow_id: 'wf-1', repo: 'o/r', issue_number: 5,
    status: 'done', message: 'PR opened for o/r#5.',
    created_at: '2026-07-03T00:00:00Z', read: false,
  },
  {
    id: 1, workflow_id: 'wf-1', repo: 'o/r', issue_number: 5,
    status: 'awaiting_plan_approval',
    message: 'Implementation plan ready for review: o/r#5.',
    created_at: '2026-07-02T00:00:00Z', read: true,
  },
]

describe('useNotifications', () => {
  it('refresh populates items and unreadCount', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(sample), { status: 200 })),
    )
    const { items, unreadCount, refresh } = useNotifications()
    await refresh()
    expect(items.value.map((n) => n.id)).toEqual([2, 1])
    expect(unreadCount.value).toBe(1)
  })

  it('markRead posts then refreshes', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      String(input).includes('/read')
        ? new Response(JSON.stringify({ status: 'ok' }), { status: 200 })
        : new Response(JSON.stringify(sample), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const { markRead } = useNotifications()
    await markRead(1)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/notifications/1/read'),
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('start polls on an interval until stop', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(sample), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const { start, stop } = useNotifications()
    start()
    await vi.advanceTimersByTimeAsync(0)
    const afterStart = fetchMock.mock.calls.length
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetchMock.mock.calls.length).toBeGreaterThan(afterStart)
    stop()
    const afterStop = fetchMock.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(fetchMock.mock.calls.length).toBe(afterStop)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test`
Expected: FAIL with a module-not-found error for
`../../src/composables/useNotifications`.

- [ ] **Step 3: Implement**

Create `frontend/src/types/notifications.ts`:

```typescript
export interface Notification {
  id: number
  workflow_id: string
  repo: string
  issue_number: number
  status: string
  message: string
  created_at: string
  read: boolean
}
```

Create `frontend/src/composables/useNotifications.ts`:

```typescript
import { computed, ref } from 'vue'
import { api } from '../api'
import type { Notification } from '../types/notifications'

const items = ref<Notification[]>([])
let poll: ReturnType<typeof setInterval> | null = null

export function useNotifications() {
  async function refresh(): Promise<void> {
    items.value = await api.get<Notification[]>('/api/notifications')
  }

  async function markRead(id: number): Promise<void> {
    await api.post(`/api/notifications/${id}/read`)
    await refresh()
  }

  function start(): void {
    if (poll) return
    void refresh()
    poll = setInterval(() => void refresh(), 5000)
  }

  function stop(): void {
    if (poll) {
      clearInterval(poll)
      poll = null
    }
  }

  const unreadCount = computed(() => items.value.filter((n) => !n.read).length)

  return { items, unreadCount, refresh, markRead, start, stop }
}
```

Create `frontend/src/components/NotificationCenter.vue`:

```vue
<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useNotifications } from '../composables/useNotifications'
import { useWorkflows } from '../composables/useWorkflows'

const emit = defineEmits<{ navigate: [] }>()
const { items, unreadCount, markRead, start, stop } = useNotifications()
const { select } = useWorkflows()
const open = ref(false)

onMounted(start)
onUnmounted(stop)

async function onClick(id: number, workflowId: string): Promise<void> {
  await markRead(id)
  select(workflowId)
  open.value = false
  emit('navigate')
}
</script>

<template>
  <div class="notif">
    <button class="notif__bell" @click="open = !open" aria-label="Notifications">
      <span aria-hidden="true">🔔</span>
      <span v-if="unreadCount" class="notif__badge mono">{{ unreadCount }}</span>
    </button>
    <div v-if="open" class="notif__panel">
      <p v-if="!items.length" class="notif__empty mono">No notifications yet</p>
      <button v-for="n in items" :key="n.id" class="notif__item"
        :class="{ 'notif__item--unread': !n.read }"
        @click="onClick(n.id, n.workflow_id)">
        <span class="notif__msg">{{ n.message }}</span>
        <span class="notif__time mono">
          {{ new Date(n.created_at).toLocaleString() }}
        </span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.notif { position: relative; }
.notif__bell {
  position: relative; background: none; border: 1px solid var(--line);
  border-radius: 999px; width: 34px; height: 34px; cursor: pointer;
  color: var(--text-hi); font-size: 15px; display: grid; place-items: center;
}
.notif__bell:hover { border-color: var(--idle); background: var(--ink-700); }
.notif__badge {
  position: absolute; top: -4px; right: -4px; background: var(--err);
  color: var(--ink-900); font-size: 10px; font-weight: 700; border-radius: 999px;
  min-width: 16px; height: 16px; display: grid; place-items: center; padding: 0 3px;
}
.notif__panel {
  position: absolute; top: 42px; right: 0; width: 320px; max-height: 360px;
  overflow-y: auto; background: var(--ink-800); border: 1px solid var(--line);
  border-radius: var(--r-md); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35); z-index: 20;
}
.notif__empty { padding: 14px; color: var(--text-dim); font-size: 12px; }
.notif__item {
  display: flex; flex-direction: column; gap: 3px; width: 100%; text-align: left;
  background: none; border: none; border-bottom: 1px solid var(--line-soft);
  padding: 10px 14px; cursor: pointer; color: var(--text-mid);
}
.notif__item:hover { background: var(--ink-700); }
.notif__item--unread { color: var(--text-hi); }
.notif__item--unread .notif__msg::before { content: '● '; color: var(--signal); }
.notif__msg { font-size: 12.5px; }
.notif__time { font-size: 10.5px; color: var(--text-dim); }
</style>
```

`frontend/src/App.vue` — wire it in. Add the import:

```typescript
import NotificationCenter from './components/NotificationCenter.vue'
```

Add it to the topbar, right before the closing `</header>` tag,
inside the existing `<div class="status">` sibling position:

```html
      <div class="status" :class="running ? 'status--live' : 'status--idle'">
        <span class="status__dot" />
        <span class="status__label mono">{{ running ? 'live' : 'idle' }}</span>
      </div>
      <NotificationCenter @navigate="view = 'workflows'" />
```

(the `NotificationCenter` line is new, added right after the
existing `.status` div, still inside `<header class="topbar">`)

- [ ] **Step 4: Run tests + typecheck**

Run: `npm test` and `npx vue-tsc -b`
Expected: all pass, no type errors.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(frontend): add notification center with bell badge"
```

---

### Task 7: Verification & docs

**Files:**
- Modify: `docs/superpowers/plans/kestrel-roadmap.md`
- Delete: `docs/superpowers/plans/2026-07-01-kestrel-m-g-ui.md`

- [ ] **Step 1: Full suites**

Run: `cd backend && uv run alembic upgrade head && uv run pytest -q`
Run: `cd frontend && npm test && npx vue-tsc -b`
Expected: migration 0003 applies cleanly; all backend and frontend
tests pass; no type errors.

- [ ] **Step 2: Manual E2E (real run, through the browser)**

1. Ensure the browser's target backend is running the latest code
   (restart if not — `recover()` will reload in-flight runs).
2. Open the Workflows view, select any run with telemetry (or
   start a fresh one). Confirm the "Live telemetry" feed now shows
   typed cards — chat bubbles, collapsed tool-call disclosures,
   thinking chips, a result banner — instead of raw JSON lines,
   and that clicking "{ }" on any card reveals its exact raw
   payload.
3. Drive a run to any `awaiting_*` gate (or reuse one already
   there). Confirm the bell badge in the topbar shows an unread
   count without a page reload (within 5s).
4. Click the bell, click the notification: confirm it switches to
   the Workflows view with that exact run selected, and the badge
   count decrements.
5. Approve the run through to `done`; confirm a second
   notification appears for the PR.

- [ ] **Step 3: Docs + close**

Roadmap: tick M-G, point it at this plan, add a status-log row
(note the dropped dashboard/timeline scope and the polling-not-SSE
deviation). Delete the superseded draft:

```bash
git rm docs/superpowers/plans/2026-07-01-kestrel-m-g-ui.md
```

```bash
git add -A
git commit -m "docs: close milestone M-G (events & notifications)"
```

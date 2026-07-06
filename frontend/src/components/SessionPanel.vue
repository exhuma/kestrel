<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useSessions } from '../composables/useSessions'
import type { SessionEvent } from '../types/sessions'

const {
  sessions,
  events,
  loading,
  error,
  refresh,
  start,
  resume,
  watchEvents,
  stopEvents,
  remove,
} = useSessions()

const prompt = ref('Write a haiku about the sea into poem.txt')
const followUp = ref('Now revise it to be about mountains instead.')
const current = ref<string | null>(null)

// Client-side receipt time per event — honest "streamed at" telemetry,
// kept parallel to events so the composable stays contract-stable.
const stamps = ref<string[]>([])
const feedEl = ref<HTMLElement | null>(null)

watch(
  () => events.value.length,
  async (n) => {
    if (n < stamps.value.length) stamps.value = []
    while (stamps.value.length < n) {
      stamps.value.push(
        new Date().toLocaleTimeString('en-GB', { hour12: false }),
      )
    }
    await nextTick()
    if (feedEl.value) feedEl.value.scrollTop = feedEl.value.scrollHeight
  },
)

onMounted(refresh)

async function onStart(): Promise<void> {
  const id = await start(prompt.value)
  if (id) {
    current.value = id
    watchEvents(id)
  }
}

async function onResume(): Promise<void> {
  if (!current.value) return
  const id = await resume(current.value, followUp.value)
  if (id) watchEvents(id)
}

function onSelect(id: string): void {
  current.value = id
  watchEvents(id)
}

async function onDelete(id: string): Promise<void> {
  if (!confirm('Abandon this session? This drops the work locally.')) return
  await remove(id)
  if (current.value === id) {
    current.value = null
    stopEvents()
  }
}

const currentStatus = computed(() => {
  const s = sessions.value.find((x) => x.session_id === current.value)
  return s?.status ?? (current.value ? 'running' : 'standby')
})

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-3)}` : id
}

// Session start, shown two ways: a glanceable "x ago" and the exact
// local wall-clock — useful when correlating a session with logs.
function relTime(iso: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (secs < 60) return `${secs}s ago`
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}
function absTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const p = (n: number): string => String(n).padStart(2, '0')
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}`
  )
}

// Map a canonical event to a semantic tone + glyph. Tone drives the --c
// colour custom property shared by the dot, rule, and labels. Reads the
// canonical vocabulary — no backend-specific raw parsing.
function tone(e: SessionEvent): string {
  switch (e.kind) {
    case 'result':
      return e.is_error ? 'err' : 'ok'
    case 'tool_use':
    case 'tool_result':
      return 'tool'
    case 'assistant_text':
      return 'agent'
    case 'user_text':
      return 'user'
    case 'error':
      return 'err'
    default:
      return 'sys'
  }
}
function glyph(e: SessionEvent): string {
  return (
    {
      ok: '✓',
      err: '✕',
      agent: '▸',
      user: '▹',
      tool: '⚙',
      sys: '◇',
    }[tone(e)] ?? '·'
  )
}
function statusTone(s: string): string {
  if (s === 'running') return 'agent'
  if (s === 'idle') return 'ok'
  if (s === 'error') return 'err'
  return 'sys'
}
function subtype(e: SessionEvent): string | null {
  return typeof e.subtype === 'string' ? e.subtype : null
}
// Surface the human-meaningful line from a canonical event, falling back
// to compact JSON of the native payload for shapes we don't recognise.
function preview(e: SessionEvent): string {
  switch (e.kind) {
    case 'assistant_text':
    case 'user_text':
    case 'tool_result':
      return e.text || '—'
    case 'tool_use': {
      const call = `${e.tool_name ?? ''}${
        e.tool_summary ? ` · ${e.tool_summary}` : ''
      }`
      return e.text ? `${e.text}   ${call}` : call
    }
    case 'thinking':
      return `~${e.tokens ?? 0} tok`
    case 'system': {
      const servers = e.mcp_servers?.length
        ? e.mcp_servers
            .map((m) => `${m.name}${m.status ? ` (${m.status})` : ''}`)
            .join(', ')
        : ''
      // On the init frame, always report MCP — "none" is itself the answer
      // to "did my configured MCP server load into this session?".
      const mcp =
        e.subtype === 'init'
          ? `MCP: ${servers || 'none'}`
          : servers && `MCP: ${servers}`
      const tools = e.tools?.length ? `tools: ${e.tools.join(', ')}` : ''
      const bits = [e.model, mcp, tools].filter(Boolean)
      return bits.length ? bits.join('   ·   ') : (e.summary ?? '—')
    }
    case 'rate_limit':
      return e.status ?? '—'
    case 'result':
      return e.text || '—'
    default: {
      const clone: Record<string, unknown> = { ...(e.native ?? {}) }
      delete clone.type
      delete clone.session_id
      delete clone.subtype
      const s = JSON.stringify(clone)
      if (!s || s === '{}') return '—'
      return s.length > 200 ? `${s.slice(0, 200)}…` : s
    }
  }
}
</script>

<template>
  <div class="console">
    <aside class="rail">
      <div class="rail__block">
        <div class="eyebrow">Dispatch</div>
        <textarea
          v-model="prompt"
          class="field"
          rows="4"
          placeholder="Describe the task for a new agent…"
        />
        <button
          class="btn btn--primary"
          :disabled="loading || !prompt.trim()"
          @click="onStart"
        >
          <span aria-hidden="true">⟐</span> Launch session
        </button>
      </div>

      <div class="rail__block">
        <div class="eyebrow">Follow-up</div>
        <textarea
          v-model="followUp"
          class="field"
          rows="3"
          :disabled="!current"
          placeholder="Send more input to the selected session…"
        />
        <button
          class="btn btn--ghost"
          :disabled="!current || loading"
          @click="onResume"
        >
          Resume session
        </button>
      </div>

      <div class="rail__block rail__block--grow">
        <div class="rail__head">
          <span class="eyebrow">Sessions</span>
          <span class="pill mono">{{ sessions.length }}</span>
        </div>
        <div class="sessions scroll">
          <div v-for="s in sessions" :key="s.session_id" class="scard-wrap">
            <button
              class="scard"
              :class="{ 'scard--active': s.session_id === current }"
              @click="onSelect(s.session_id)"
            >
              <span class="scard__id mono">{{ shortId(s.session_id) }}</span>
              <span class="scard__meta" :class="`t-${statusTone(s.status)}`">
                <span class="scard__dot" />
                {{ s.status }}
                <span class="scard__sep">·</span>
                {{ s.event_count }} ev
              </span>
              <span v-if="s.workflow" class="scard__wf mono">
                ⟐ {{ s.workflow }}
              </span>
              <span v-if="s.created_at" class="scard__time mono">
                {{ relTime(s.created_at) }} · {{ absTime(s.created_at) }}
              </span>
            </button>
            <button
              class="scard__del"
              title="Abandon session"
              aria-label="Abandon session"
              @click.stop="onDelete(s.session_id)"
            >
              ✕
            </button>
          </div>
          <p v-if="!sessions.length" class="sessions__empty mono">
            No sessions dispatched yet
          </p>
        </div>
      </div>
    </aside>

    <section class="stage">
      <transition name="drop">
        <div v-if="error" class="banner" role="alert">
          <span class="banner__glyph" aria-hidden="true">!</span>
          <span class="banner__text">{{ error }}</span>
          <button
            class="banner__close"
            aria-label="Dismiss"
            @click="error = null"
          >
            ✕
          </button>
        </div>
      </transition>

      <header class="stage__head">
        <div class="stage__title">
          <span class="eyebrow">Session</span>
          <span class="stage__id mono">{{ current ?? '—' }}</span>
        </div>
        <div class="stage__right">
          <span class="chip" :class="`t-${statusTone(currentStatus)}`">
            <span class="chip__dot" />
            <span class="mono">{{ currentStatus }}</span>
          </span>
          <span class="stage__count mono">{{ events.length }} events</span>
        </div>
      </header>

      <div ref="feedEl" class="feed scroll">
        <div v-if="!events.length" class="feed__empty">
          <span class="feed__ping" aria-hidden="true" />
          <p class="feed__empty-title">Awaiting dispatch</p>
          <p class="feed__empty-sub mono">
            Launch a session to stream its telemetry here.
          </p>
        </div>

        <ol v-else class="timeline">
          <li
            v-for="(e, i) in events"
            :key="i"
            class="ev"
            :class="`t-${tone(e)}`"
          >
            <div class="ev__rail">
              <span class="ev__dot">{{ glyph(e) }}</span>
            </div>
            <div class="ev__body">
              <div class="ev__meta">
                <span class="ev__tick mono">{{ stamps[i] }}</span>
                <span class="ev__type">{{ e.kind }}</span>
                <span v-if="subtype(e)" class="ev__sub mono">{{
                  subtype(e)
                }}</span>
              </div>
              <div class="ev__payload mono">{{ preview(e) }}</div>
            </div>
          </li>
        </ol>
      </div>
    </section>
  </div>
</template>

<style scoped>
.console {
  display: flex;
  height: 100%;
  min-height: 0;
}

/* ---- Dispatch rail ---- */
.rail {
  width: 340px;
  flex: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 22px 18px;
  border-right: 1px solid var(--line);
  background: var(--ink-800);
  overflow: hidden;
}
.rail__block {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 0 18px;
  border-bottom: 1px solid var(--line-soft);
}
.rail__block:first-child {
  padding-top: 0;
}
.rail__block--grow {
  flex: 1;
  min-height: 0;
  border-bottom: none;
  padding-bottom: 0;
}
.rail__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.pill {
  font-size: 11px;
  color: var(--text-mid);
  background: var(--ink-700);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 1px 9px;
}

.sessions {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  min-height: 0;
  padding-right: 4px;
}
.scard {
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 11px 13px;
  background: var(--ink-700);
  border: 1px solid var(--line);
  border-left: 2px solid var(--line);
  border-radius: var(--r-md);
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background 0.15s ease;
}
.scard:hover {
  background: var(--ink-650);
}
.scard--active {
  border-left-color: var(--signal);
  background: var(--ink-650);
}
.scard-wrap {
  position: relative;
  display: flex;
}
.scard-wrap .scard {
  flex: 1;
  width: 100%;
  padding-right: 30px;
}
.scard__del {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  cursor: pointer;
  opacity: 0;
  transition:
    opacity 0.12s ease,
    color 0.12s ease,
    background 0.12s ease;
}
.scard-wrap:hover .scard__del,
.scard__del:focus-visible {
  opacity: 1;
}
.scard__del:hover {
  color: var(--err);
  background: color-mix(in srgb, var(--err) 15%, transparent);
}
.scard__id {
  font-size: 12.5px;
  color: var(--text-hi);
}
.scard__meta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-mid);
}
.scard__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--c, var(--idle));
}
.scard__sep {
  color: var(--text-dim);
}
.scard__wf {
  align-self: flex-start;
  font-size: 11px;
  color: var(--signal);
  background: color-mix(in srgb, var(--signal) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--signal) 30%, transparent);
  border-radius: 999px;
  padding: 1px 8px;
}
.scard__time {
  font-size: 10.5px;
  color: var(--text-dim);
  letter-spacing: 0.02em;
}
.sessions__empty {
  color: var(--text-dim);
  font-size: 12px;
  padding: 8px 2px;
}

/* ---- Stage ---- */
.stage {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.banner {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 16px 24px 0;
  padding: 11px 14px;
  border: 1px solid color-mix(in srgb, var(--err) 45%, var(--line));
  border-left: 3px solid var(--err);
  border-radius: var(--r-md);
  background: color-mix(in srgb, var(--err) 12%, var(--ink-800));
  color: var(--text-hi);
  font-size: 13px;
}
.banner__glyph {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  flex: none;
  border-radius: 50%;
  background: var(--err);
  color: var(--ink-900);
  font-weight: 700;
  font-size: 13px;
}
.banner__text {
  flex: 1;
}
.banner__close {
  background: none;
  border: none;
  color: var(--text-mid);
  cursor: pointer;
  font-size: 12px;
  padding: 4px;
}
.banner__close:hover {
  color: var(--text-hi);
}

.stage__head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px 18px;
  border-bottom: 1px solid var(--line);
}
.stage__title {
  display: flex;
  align-items: baseline;
  gap: 12px;
  min-width: 0;
}
.stage__id {
  font-size: 15px;
  color: var(--text-hi);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stage__right {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: none;
}
.stage__count {
  font-size: 12px;
  color: var(--text-dim);
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 11px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--c, var(--idle)) 40%, var(--line));
  background: color-mix(in srgb, var(--c, var(--idle)) 12%, transparent);
  font-size: 11.5px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--c, var(--idle));
}
.chip__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--c, var(--idle));
}

/* ---- Signature: live telemetry feed ---- */
.feed {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 24px 28px;
}
.feed__empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
}
.feed__ping {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1.5px solid var(--line);
  position: relative;
  margin-bottom: 8px;
}
.feed__ping::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1.5px solid var(--signal);
  opacity: 0.5;
  animation: ping 2.4s ease-out infinite;
}
@keyframes ping {
  0% {
    transform: scale(0.5);
    opacity: 0.6;
  }
  100% {
    transform: scale(1.4);
    opacity: 0;
  }
}
.feed__empty-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-mid);
}
.feed__empty-sub {
  margin: 0;
  font-size: 12px;
  color: var(--text-dim);
}

.timeline {
  list-style: none;
  margin: 0;
  padding: 14px 0 0;
}
.ev {
  --c: var(--idle);
  display: grid;
  grid-template-columns: 34px 1fr;
  gap: 14px;
}
.ev.t-sys {
  --c: var(--idle);
}
.ev.t-agent {
  --c: var(--signal);
}
.ev.t-user {
  --c: var(--user);
}
.ev.t-tool {
  --c: var(--warn);
}
.ev.t-ok {
  --c: var(--ok);
}
.ev.t-err {
  --c: var(--err);
}

.ev__rail {
  position: relative;
  display: flex;
  justify-content: center;
}
.ev__rail::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  background: var(--line);
  transform: translateX(-0.5px);
}
.ev:first-child .ev__rail::before {
  top: 11px;
}
.ev:last-child .ev__rail::before {
  bottom: auto;
  height: 11px;
}
.ev__dot {
  position: relative;
  z-index: 1;
  width: 22px;
  height: 22px;
  margin-top: 1px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 11px;
  line-height: 1;
  color: var(--c);
  background: var(--ink-700);
  border: 1px solid color-mix(in srgb, var(--c) 55%, var(--line));
  box-shadow: 0 0 0 3px var(--ink-900);
}
.ev__body {
  padding-bottom: 16px;
  min-width: 0;
}
.ev__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 3px;
}
.ev__tick {
  font-size: 11.5px;
  color: var(--text-dim);
  flex: none;
}
.ev__type {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-hi);
}
.ev__sub {
  font-size: 11px;
  color: var(--c);
  border: 1px solid color-mix(in srgb, var(--c) 35%, var(--line));
  border-radius: 999px;
  padding: 0 8px;
  background: color-mix(in srgb, var(--c) 10%, transparent);
}
.ev__payload {
  font-size: 12px;
  color: var(--text-mid);
  word-break: break-word;
  white-space: pre-wrap;
  line-height: 1.5;
}

/* status tones reused on rail cards + chip via --c */
.t-sys {
  --c: var(--idle);
}
.t-agent {
  --c: var(--signal);
}
.t-user {
  --c: var(--user);
}
.t-tool {
  --c: var(--warn);
}
.t-ok {
  --c: var(--ok);
}
.t-err {
  --c: var(--err);
}

.drop-enter-active,
.drop-leave-active {
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
}
.drop-enter-from,
.drop-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

@media (max-width: 860px) {
  .console {
    flex-direction: column;
  }
  .rail {
    width: 100%;
    border-right: none;
    border-bottom: 1px solid var(--line);
    max-height: 46%;
  }
}
</style>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useSessions } from '../composables/useSessions'
import ConsoleShell from './ConsoleShell.vue'
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
// Semantic tone → Vuetify theme colour (undefined = neutral default).
const TONE_COLOR: Record<string, string | undefined> = {
  agent: 'primary',
  user: 'info',
  tool: 'warning',
  ok: 'success',
  err: 'error',
  sys: undefined,
}
function toneColor(t: string): string | undefined {
  return TONE_COLOR[t]
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
  <ConsoleShell>
    <template #rail>
      <div class="pa-4">
        <div class="text-overline text-medium-emphasis mb-2">Dispatch</div>
        <v-textarea
          v-model="prompt"
          rows="4"
          class="mb-2"
          label="Describe the task for a new agent…"
        />
        <v-btn
          block
          color="primary"
          prepend-icon="mdi-rocket-launch-outline"
          :disabled="loading || !prompt.trim()"
          @click="onStart"
        >
          Launch session
        </v-btn>
      </div>
      <v-divider />
      <div class="pa-4">
        <div class="text-overline text-medium-emphasis mb-2">Follow-up</div>
        <v-textarea
          v-model="followUp"
          rows="3"
          class="mb-2"
          :disabled="!current"
          label="Send more input to the selected session…"
        />
        <v-btn
          block
          variant="tonal"
          :disabled="!current || loading"
          @click="onResume"
        >
          Resume session
        </v-btn>
      </div>
      <v-divider />
      <div class="d-flex align-center justify-space-between px-4 py-2">
        <span class="text-overline text-medium-emphasis">Sessions</span>
        <v-chip size="small" variant="tonal">{{ sessions.length }}</v-chip>
      </div>
      <v-list v-if="sessions.length" nav>
        <v-list-item
          v-for="s in sessions"
          :key="s.session_id"
          :active="s.session_id === current"
          @click="onSelect(s.session_id)"
        >
          <v-list-item-title class="d-flex align-center ga-2">
            <v-icon
              icon="mdi-circle"
              :color="toneColor(statusTone(s.status))"
              size="x-small"
            />
            {{ shortId(s.session_id) }}
          </v-list-item-title>
          <v-list-item-subtitle>
            {{ s.status }} · {{ s.event_count }} ev
            <template v-if="s.created_at">
              · {{ relTime(s.created_at) }}</template
            >
          </v-list-item-subtitle>
          <v-list-item-subtitle v-if="s.workflow">
            ⟐ {{ s.workflow }}
          </v-list-item-subtitle>
          <template #append>
            <v-btn
              icon="mdi-close"
              size="x-small"
              variant="text"
              title="Abandon session"
              aria-label="Abandon session"
              @click.stop="onDelete(s.session_id)"
            />
          </template>
        </v-list-item>
      </v-list>
      <div v-else class="px-4 text-medium-emphasis text-body-2">
        No sessions dispatched yet
      </div>
    </template>

    <v-alert
      v-if="error"
      type="error"
      closable
      density="compact"
      class="ma-4 mb-0"
      role="alert"
      @click:close="error = null"
    >
      {{ error }}
    </v-alert>

    <div class="d-flex align-center justify-space-between ga-4 pa-4 border-b">
      <div class="d-flex align-center ga-2 text-truncate">
        <span class="text-overline text-medium-emphasis">Session</span>
        <span class="stage__id text-body-1">{{ current ?? '—' }}</span>
      </div>
      <div class="d-flex align-center ga-3 flex-shrink-0">
        <v-chip size="small" :color="toneColor(statusTone(currentStatus))">
          {{ currentStatus }}
        </v-chip>
        <span class="text-caption text-medium-emphasis">
          {{ events.length }} events
        </span>
      </div>
    </div>

    <div ref="feedEl" class="feed flex-1-1 pa-4">
      <v-empty-state
        v-if="!events.length"
        icon="mdi-radar"
        headline="Awaiting dispatch"
        text="Launch a session to stream its telemetry here."
      />

      <v-timeline
        v-else
        density="compact"
        side="end"
        align="start"
        truncate-line="both"
      >
        <v-timeline-item
          v-for="(e, i) in events"
          :key="i"
          :dot-color="toneColor(tone(e))"
          size="x-small"
        >
          <template #icon>
            <span class="ev__glyph">{{ glyph(e) }}</span>
          </template>
          <div class="d-flex align-center ga-2 mb-1 flex-wrap">
            <span class="text-caption text-medium-emphasis">{{
              stamps[i]
            }}</span>
            <span class="text-body-2 font-weight-medium">{{ e.kind }}</span>
            <v-chip
              v-if="subtype(e)"
              size="x-small"
              variant="tonal"
              :color="toneColor(tone(e))"
            >
              {{ subtype(e) }}
            </v-chip>
          </div>
          <div class="ev__payload text-body-2 text-medium-emphasis">
            {{ preview(e) }}
          </div>
        </v-timeline-item>
      </v-timeline>
    </div>
  </ConsoleShell>
</template>

<style scoped>
.stage__id {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.feed {
  overflow-y: auto;
}
.ev__glyph {
  font-size: 10px;
  line-height: 1;
}
.ev__payload {
  word-break: break-word;
  white-space: pre-wrap;
  line-height: 1.5;
}
</style>

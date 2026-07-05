<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useWorkflows } from '../composables/useWorkflows'
import QuestionnaireForm from './QuestionnaireForm.vue'
import { createPendingInterviewParser } from '../lib/questionnaire'
import EventCard from './EventCard.vue'
import { toViewModel } from '../lib/eventView'

// One parser instance for the whole panel: it memoizes on
// (workflow id, refine_round) so an SSE tick that doesn't actually
// change the questionnaire returns the same object reference instead
// of churning a fresh one on every update.
const parsePendingInterview = createPendingInterviewParser()

const { workflows, current, events, error, refresh, select, ensureLive,
  streamSession, closeSession, createWorkflow, reply, submitAnswers,
  saveDraft, approve, reject, stop, remove } = useWorkflows()

const repo = ref('owner/name')
const issueNumber = ref<number>(1)
const answer = ref('')
const edited = ref('')
const feedback = ref('')
const busy = ref<'create' | 'approve' | 'reject' | 'reply'
  | 'changes' | null>(null)

onMounted(() => {
  void refresh()
  ensureLive()
})
onUnmounted(stop)

const STEP_LABELS = ['refine', 'plan', 'implement'] as const

const activeStep = computed(() =>
  current.value?.steps.find((s) =>
    ['running', 'awaiting_input', 'awaiting_approval'].includes(s.status)),
)
const awaitingInput = computed(() => activeStep.value?.status === 'awaiting_input')
const awaitingApproval = computed(() => activeStep.value?.status === 'awaiting_approval')
const stepRunning = computed(() => activeStep.value?.status === 'running')
const pendingInterview = computed(() =>
  awaitingInput.value && current.value
    ? parsePendingInterview(current.value.id, activeStep.value ?? null)
    : null,
)
const issueUrl = computed(() =>
  current.value ? `https://github.com/${current.value.repo}/issues/${current.value.issue_number}` : '',
)

// Named specialist sessions active right now, shown as activity chips.
const activeSessions = computed(() => current.value?.active_sessions ?? [])
const expandedSession = ref<string | null>(null)
const expandedLabel = computed(() =>
  activeSessions.value.find((s) => s.session_id === expandedSession.value)
    ?.label ?? 'session',
)

function toggleSession(sessionId: string | null): void {
  if (!sessionId) return
  if (expandedSession.value === sessionId) {
    expandedSession.value = null
    closeSession()
  } else {
    expandedSession.value = sessionId
    streamSession(sessionId)
  }
}

// Collapse the telemetry drawer whenever the selected run changes.
watch(() => current.value?.id, () => {
  expandedSession.value = null
  closeSession()
})

// Close the drawer once its session is no longer active (the step
// advanced), keeping the workflow view bounded in height.
watch(activeSessions, (list) => {
  if (expandedSession.value &&
      !list.some((s) => s.session_id === expandedSession.value)) {
    expandedSession.value = null
    closeSession()
  }
})

async function onCreate(): Promise<void> {
  busy.value = 'create'
  try {
    await createWorkflow(repo.value, Number(issueNumber.value))
  } finally {
    busy.value = null
  }
}
async function onApprove(): Promise<void> {
  busy.value = 'approve'
  try {
    await approve(edited.value || undefined)
    edited.value = ''
  } finally {
    busy.value = null
  }
}
async function onReject(): Promise<void> {
  busy.value = 'reject'
  try {
    await reject()
  } finally {
    busy.value = null
  }
}
async function onRequestChanges(): Promise<void> {
  busy.value = 'changes'
  try {
    await reject(feedback.value)
    feedback.value = ''
  } finally {
    busy.value = null
  }
}
async function onReply(): Promise<void> {
  busy.value = 'reply'
  try {
    await reply(answer.value)
    answer.value = ''
  } finally {
    busy.value = null
  }
}
async function onSubmitAnswers(
  answers: Record<string, unknown>,
): Promise<void> {
  busy.value = 'reply'
  try {
    await submitAnswers(answers)
  } finally {
    busy.value = null
  }
}
async function onSaveDraft(
  answers: Record<string, unknown>,
): Promise<void> {
  try {
    await saveDraft(answers)
  } catch {
    /* draft saves are best-effort; ignore transient failures */
  }
}
async function onDelete(id: string): Promise<void> {
  if (!confirm('Abandon this workflow? This drops the local work only — '
    + 'nothing on GitHub is changed.')) return
  await remove(id)
}
function stepStatus(name: string): string {
  return current.value?.steps.find((s) => s.name === name)?.status ?? 'pending'
}
function stepTone(status: string): string {
  if (status === 'done') return 'ok'
  if (status === 'running' || status === 'awaiting_input') return 'agent'
  if (status === 'awaiting_approval') return 'warn'
  if (status === 'failed') return 'err'
  return 'sys'
}
</script>

<template>
  <div class="console">
    <aside class="rail">
      <div class="rail__block">
        <div class="eyebrow">New workflow</div>
        <input v-model="repo" class="field" placeholder="owner/name" />
        <input v-model="issueNumber" type="number" class="field" placeholder="Issue #" />
        <button class="btn btn--primary" :disabled="busy === 'create'" @click="onCreate">
          <span aria-hidden="true">⟐</span> {{ busy === 'create' ? 'Starting…' : 'Start workflow' }}
        </button>
      </div>
      <div class="rail__block rail__block--grow">
        <div class="rail__head">
          <span class="eyebrow">Runs</span>
          <span class="pill mono">{{ workflows.length }}</span>
        </div>
        <div class="sessions scroll">
          <div v-for="w in workflows" :key="w.id" class="scard-wrap">
            <button
              class="scard"
              :class="{ 'scard--active': w.id === current?.id }"
              @click="select(w.id)"
            >
              <span class="scard__id mono">{{ w.repo }}#{{ w.issue_number }}</span>
              <span class="scard__meta">
                <span v-if="w.status.startsWith('awaiting')" class="scard__dot"
                  aria-hidden="true" />
                {{ w.status }}
              </span>
            </button>
            <button
              class="scard__del"
              title="Abandon workflow"
              aria-label="Abandon workflow"
              @click.stop="onDelete(w.id)"
            >✕</button>
          </div>
          <p v-if="!workflows.length" class="sessions__empty mono">
            No workflows yet
          </p>
        </div>
      </div>
    </aside>

    <section class="stage">
      <div v-if="error" class="banner" role="alert">
        <span class="banner__glyph" aria-hidden="true">!</span>
        <span class="banner__text">{{ error }}</span>
        <button class="banner__close" @click="error = null">✕</button>
      </div>

      <div v-if="current?.error" class="banner" role="alert">
        <span class="banner__glyph" aria-hidden="true">!</span>
        <span class="banner__text">Run failed: {{ current.error }}</span>
      </div>

      <header class="stage__head" v-if="current">
        <div class="stage__title">
          <span class="eyebrow">Workflow</span>
          <a class="stage__id mono" :href="issueUrl" target="_blank" rel="noopener noreferrer">
            {{ current.repo }}#{{ current.issue_number }}
          </a>
        </div>
        <div class="tracker">
          <span
            v-for="name in STEP_LABELS"
            :key="name"
            class="tracker__step"
            :class="`t-${stepTone(stepStatus(name))}`"
          >
            <span class="tracker__dot" />{{ name }}
          </span>
          <span class="tracker__step" :class="current.pr_url ? 't-ok' : 't-sys'">
            <span class="tracker__dot" />PR
          </span>
        </div>
      </header>

      <div class="stage__body scroll" v-if="current">
        <div v-if="stepRunning" class="crew">
          <span class="eyebrow">{{ activeStep?.name }} · live</span>
          <div v-if="activeSessions.length" class="chips">
            <button
              v-for="s in activeSessions"
              :key="s.session_id ?? s.profile_id"
              type="button"
              class="chip"
              :class="[`chip--${s.badge}`,
                { 'chip--live': s.status === 'running',
                  'chip--open': expandedSession === s.session_id }]"
              :disabled="!s.session_id"
              @click="toggleSession(s.session_id)"
            >
              <span class="chip__dot" aria-hidden="true" />
              <span class="chip__label mono">{{ s.label }}</span>
            </button>
          </div>
          <div v-else class="working">
            <span class="working__pulse" aria-hidden="true" />
            <span class="mono">{{ activeStep?.name }} — agent is working…</span>
          </div>
        </div>

        <div v-if="awaitingInput || awaitingApproval" class="working working--attention"
          role="status">
          <span class="working__pulse working__pulse--warn" aria-hidden="true" />
          <span class="mono">
            {{ activeStep?.name }} —
            {{ awaitingInput ? 'the agent awaits your answers below'
              : 'awaiting your approval below' }}
          </span>
        </div>

        <div class="deliverable"
          v-if="activeStep?.deliverable && !(awaitingInput && pendingInterview)">
          <div class="eyebrow">
            {{ awaitingInput ? `${activeStep.name} — agent asks` : `${activeStep.name} deliverable` }}
          </div>
          <pre class="deliverable__text mono">{{ activeStep.deliverable }}</pre>
        </div>

        <div class="gate" v-if="awaitingApproval">
          <textarea v-model="edited" class="field" rows="4"
            :placeholder="`Optionally edit the ${activeStep?.name} deliverable before approving…`" />
          <div class="gate__actions">
            <button class="btn btn--primary" :disabled="!!busy" @click="onApprove">
              {{ busy === 'approve' ? 'Approving…' : 'Approve' }}
            </button>
            <button class="btn btn--ghost" :disabled="!!busy" @click="onReject">
              {{ busy === 'reject' ? 'Rejecting…' : 'Reject' }}
            </button>
          </div>
          <textarea v-model="feedback" class="field" rows="3"
            placeholder="Or describe what to change and send it back…" />
          <button class="btn" :disabled="!feedback.trim() || !!busy"
            @click="onRequestChanges">
            {{ busy === 'changes' ? 'Sending…' : 'Request changes' }}
          </button>
        </div>

        <div class="gate" v-if="awaitingInput">
          <QuestionnaireForm v-if="pendingInterview"
            :questionnaire="pendingInterview.questionnaire"
            :draft-answers="pendingInterview.draft_answers"
            :round="pendingInterview.round"
            @submit="onSubmitAnswers" @save-draft="onSaveDraft" />
          <template v-else>
            <textarea v-model="answer" class="field" rows="3"
              placeholder="Answer the agent's questions…" />
            <button class="btn btn--primary" :disabled="!!busy" @click="onReply">
              {{ busy === 'reply' ? 'Sending…' : 'Send reply' }}
            </button>
          </template>
        </div>

        <a v-if="current.pr_url" class="pr-link" :href="current.pr_url" target="_blank"
          rel="noopener noreferrer">View pull request →</a>

        <div class="drawer" v-if="expandedSession">
          <div class="drawer__head">
            <span class="eyebrow">Session · {{ expandedLabel }}</span>
            <button type="button" class="drawer__close mono"
              @click="toggleSession(expandedSession)">Hide ✕</button>
          </div>
          <div class="drawer__feed scroll">
            <EventCard v-for="(e, i) in events" :key="i"
              :event="toViewModel(e)" />
            <p v-if="!events.length" class="drawer__empty mono">
              Waiting for activity…
            </p>
          </div>
        </div>
      </div>

      <div class="feed__empty" v-else>
        <p class="feed__empty-title">No workflow selected</p>
        <p class="feed__empty-sub mono">Start one from an issue on the left.</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* Reuses tokens from styles/theme.css. Layout mirrors SessionPanel. */
.console { display: flex; height: 100%; min-height: 0; }
.rail {
  width: 340px; flex: none; display: flex; flex-direction: column; gap: 4px;
  padding: 22px 18px; border-right: 1px solid var(--line); background: var(--ink-800);
  overflow: hidden;
}
.rail__block {
  display: flex; flex-direction: column; gap: 10px; padding: 14px 0 18px;
  border-bottom: 1px solid var(--line-soft);
}
.rail__block:first-child { padding-top: 0; }
.rail__block--grow { flex: 1; min-height: 0; border-bottom: none; }
.rail__head { display: flex; align-items: center; justify-content: space-between; }
.pill {
  font-size: 11px; color: var(--text-mid); background: var(--ink-700);
  border: 1px solid var(--line); border-radius: 999px; padding: 1px 9px;
}
.sessions { margin-top: 12px; display: flex; flex-direction: column; gap: 8px;
  overflow-y: auto; min-height: 0; }
.scard {
  text-align: left; display: flex; flex-direction: column; gap: 6px;
  padding: 11px 13px; background: var(--ink-700); border: 1px solid var(--line);
  border-left: 2px solid var(--line); border-radius: var(--r-md); cursor: pointer;
}
.scard--active { border-left-color: var(--signal); background: var(--ink-650); }
.scard-wrap { position: relative; display: flex; }
.scard-wrap .scard { flex: 1; width: 100%; padding-right: 30px; }
.scard__del {
  position: absolute; top: 8px; right: 8px; width: 20px; height: 20px;
  display: grid; place-items: center; border: none; border-radius: 4px;
  background: transparent; color: var(--text-dim); font-size: 12px;
  cursor: pointer; opacity: 0;
  transition: opacity 0.12s ease, color 0.12s ease, background 0.12s ease;
}
.scard-wrap:hover .scard__del, .scard__del:focus-visible { opacity: 1; }
.scard__del:hover {
  color: var(--err); background: color-mix(in srgb, var(--err) 15%, transparent);
}
.scard__id { font-size: 12.5px; color: var(--text-hi); }
.scard__meta { font-size: 11.5px; color: var(--text-mid); }
.sessions__empty { color: var(--text-dim); font-size: 12px; padding: 8px 2px; }
.stage { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }
.stage__head {
  flex: none; display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding: 20px 24px 18px; border-bottom: 1px solid var(--line);
}
.stage__title { display: flex; align-items: baseline; gap: 12px; }
.stage__id {
  font-size: 15px; color: var(--text-hi); text-decoration: none;
  border-bottom: 1px dotted var(--line);
}
.stage__id:hover { color: var(--signal); border-bottom-color: var(--signal); }
.tracker { display: flex; gap: 14px; }
.tracker__step {
  --c: var(--idle); display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--c);
}
.tracker__dot { width: 8px; height: 8px; border-radius: 50%; background: var(--c); }
.t-sys { --c: var(--idle); } .t-agent { --c: var(--signal); }
.t-warn { --c: var(--warn); } .t-ok { --c: var(--ok); } .t-err { --c: var(--err); }
.stage__body { flex: 1; min-height: 0; overflow-y: auto; padding: 18px 24px; display: flex; flex-direction: column; gap: 18px; }
.deliverable__text {
  white-space: pre-wrap; word-break: break-word; background: var(--ink-750);
  border: 1px solid var(--line); border-radius: var(--r-md); padding: 12px 14px;
  font-size: 12.5px; color: var(--text-hi); margin: 6px 0 0;
}
.working {
  display: flex; align-items: center; gap: 10px; padding: 10px 14px;
  border: 1px solid var(--line); border-radius: var(--r-md);
  background: var(--ink-700); color: var(--text-mid); font-size: 12.5px;
}
.working__pulse {
  width: 8px; height: 8px; border-radius: 50%; background: var(--signal);
  box-shadow: 0 0 0 0 rgba(53, 230, 201, 0.45);
  animation: working-pulse 1.4s ease-out infinite;
}
@keyframes working-pulse {
  0% { box-shadow: 0 0 0 0 rgba(53, 230, 201, 0.45); }
  70% { box-shadow: 0 0 0 7px rgba(53, 230, 201, 0); }
  100% { box-shadow: 0 0 0 0 rgba(53, 230, 201, 0); }
}
.working--attention { border-color: var(--warn); color: var(--text-hi); }
.working__pulse--warn {
  background: var(--warn);
  animation: attention-pulse 1.4s ease-out infinite;
}
.scard__dot {
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  margin-right: 6px; background: var(--warn);
  animation: attention-pulse 1.4s ease-out infinite;
}
@keyframes attention-pulse {
  0% {
    box-shadow: 0 0 0 0
      color-mix(in srgb, var(--warn) 45%, transparent);
  }
  70% { box-shadow: 0 0 0 7px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}
.gate { display: flex; flex-direction: column; gap: 10px; }
.gate__actions { display: flex; gap: 10px; }
.gate__actions .btn { width: auto; padding-left: 22px; padding-right: 22px; }
.pr-link { color: var(--signal); font-weight: 600; text-decoration: none; }

/* Crew band — the named specialist sessions active right now. This is
   the workflow view's signature: mnemonics only, each pulsing while its
   session is live, the verbose telemetry tucked away until asked for. */
.crew { display: flex; flex-direction: column; gap: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip {
  --c: var(--idle);
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 12px 6px 10px;
  background: var(--ink-700); color: var(--text-mid);
  border: 1px solid var(--line); border-radius: 999px;
  cursor: pointer; font-family: var(--font-sans);
  transition: border-color 0.15s ease, background 0.15s ease,
    color 0.15s ease;
}
.chip:hover:not(:disabled) { border-color: var(--c); color: var(--text-hi); }
.chip:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--signal-glow); }
.chip:disabled { cursor: default; opacity: 0.6; }
.chip__label { font-size: 12.5px; }
.chip__dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--c);
  flex: none;
}
.chip--live .chip__dot {
  box-shadow: 0 0 0 0 var(--c);
  animation: chip-pulse 1.6s ease-out infinite;
}
.chip--open {
  border-color: var(--c); color: var(--text-hi);
  background: var(--ink-650);
}
.chip--user { --c: var(--user); }
.chip--agent { --c: var(--signal); }
.chip--warn { --c: var(--warn); }
.chip--ok { --c: var(--ok); }
.chip--err { --c: var(--err); }
.chip--sys { --c: var(--idle); }
@keyframes chip-pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c) 55%, transparent); }
  70% { box-shadow: 0 0 0 6px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}

/* Telemetry drawer — opened on demand from a chip, capped in height so
   the raw event stream can never push the panel around. */
.drawer {
  display: flex; flex-direction: column; gap: 6px;
  border: 1px solid var(--line); border-radius: var(--r-md);
  background: var(--ink-750); overflow: hidden;
}
.drawer__head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 12px; border-bottom: 1px solid var(--line-soft);
}
.drawer__close {
  background: none; border: none; color: var(--text-dim);
  cursor: pointer; font-size: 11px; letter-spacing: 0.04em;
}
.drawer__close:hover { color: var(--text-hi); }
.drawer__feed {
  display: flex; flex-direction: column; gap: 4px;
  max-height: 300px; overflow-y: auto; padding: 8px 12px 12px;
}
.drawer__empty { color: var(--text-dim); font-size: 12px; padding: 6px 2px; }
.feed { display: flex; flex-direction: column; gap: 4px; }
.banner {
  display: flex; align-items: center; gap: 12px; margin: 16px 24px 0;
  padding: 11px 14px; border: 1px solid var(--err); border-left: 3px solid var(--err);
  border-radius: var(--r-md); background: color-mix(in srgb, var(--err) 12%, var(--ink-800));
  font-size: 13px;
}
.banner__glyph {
  display: grid; place-items: center; width: 20px; height: 20px; flex: none;
  border-radius: 50%; background: var(--err); color: var(--ink-900); font-weight: 700;
}
.banner__text { flex: 1; }
.banner__close { background: none; border: none; color: var(--text-mid); cursor: pointer; }
.feed__empty {
  height: 100%; display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 6px;
}
.feed__empty-title { margin: 0; font-size: 15px; font-weight: 600; color: var(--text-mid); }
.feed__empty-sub { margin: 0; font-size: 12px; color: var(--text-dim); }
</style>

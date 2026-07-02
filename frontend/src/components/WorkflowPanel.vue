<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useWorkflows } from '../composables/useWorkflows'

const { workflows, current, events, error, refresh, select, ensureLive,
  createWorkflow, reply, approve, reject, stop } = useWorkflows()

const repo = ref('owner/name')
const issueNumber = ref<number>(1)
const answer = ref('')
const edited = ref('')
const busy = ref<'create' | 'approve' | 'reject' | 'reply' | null>(null)

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
const issueUrl = computed(() =>
  current.value ? `https://github.com/${current.value.repo}/issues/${current.value.issue_number}` : '',
)

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
async function onReply(): Promise<void> {
  busy.value = 'reply'
  try {
    await reply(answer.value)
    answer.value = ''
  } finally {
    busy.value = null
  }
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
          <button
            v-for="w in workflows"
            :key="w.id"
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
        <div v-if="stepRunning" class="working">
          <span class="working__pulse" aria-hidden="true" />
          <span class="mono">{{ activeStep?.name }} — agent is working…</span>
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

        <div class="deliverable" v-if="activeStep?.deliverable">
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
        </div>

        <div class="gate" v-if="awaitingInput">
          <textarea v-model="answer" class="field" rows="3"
            placeholder="Answer the agent's questions…" />
          <button class="btn btn--primary" :disabled="!!busy" @click="onReply">
            {{ busy === 'reply' ? 'Sending…' : 'Send reply' }}
          </button>
        </div>

        <a v-if="current.pr_url" class="pr-link" :href="current.pr_url" target="_blank"
          rel="noopener noreferrer">View pull request →</a>

        <div class="feed">
          <div class="eyebrow">Live telemetry</div>
          <div v-for="(e, i) in events" :key="i" class="ev-line mono">
            <span class="ev-line__type">{{ e.type }}</span>
            {{ JSON.stringify(e.raw).slice(0, 140) }}
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
.feed { display: flex; flex-direction: column; gap: 4px; }
.ev-line { font-size: 12px; color: var(--text-mid); }
.ev-line__type { color: var(--signal); margin-right: 8px; }
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

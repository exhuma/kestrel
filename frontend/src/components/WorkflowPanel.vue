<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useWorkflows } from '../composables/useWorkflows'
import QuestionnaireForm from './QuestionnaireForm.vue'
import {
  createPendingInterviewParser,
  parseQuestionnaire,
} from '../lib/questionnaire'
import { renderMarkdown } from '../lib/markdown'
import EventCard from './EventCard.vue'
import ConsoleShell from './ConsoleShell.vue'
import { toViewModel } from '../lib/eventView'

// One parser instance for the whole panel: it memoizes on
// (workflow id, refine_round) so an SSE tick that doesn't actually
// change the questionnaire returns the same object reference instead
// of churning a fresh one on every update.
const parsePendingInterview = createPendingInterviewParser()

const {
  workflows,
  current,
  events,
  error,
  refresh,
  select,
  ensureLive,
  streamSession,
  closeSession,
  createWorkflow,
  reply,
  submitAnswers,
  saveDraft,
  approve,
  reject,
  stop,
  remove,
} = useWorkflows()

const repo = ref('owner/name')
const issueNumber = ref<number>(1)
const answer = ref('')
const edited = ref('')
const feedback = ref('')
const busy = ref<'create' | 'approve' | 'reject' | 'reply' | 'changes' | null>(
  null,
)

onMounted(() => {
  void refresh()
  ensureLive()
})
onUnmounted(stop)

const STEP_LABELS = ['refine', 'plan', 'implement'] as const

const activeStep = computed(() =>
  current.value?.steps.find((s) =>
    ['running', 'awaiting_input', 'awaiting_approval'].includes(s.status),
  ),
)
const awaitingInput = computed(
  () => activeStep.value?.status === 'awaiting_input',
)
const awaitingApproval = computed(
  () => activeStep.value?.status === 'awaiting_approval',
)
const stepRunning = computed(() => activeStep.value?.status === 'running')
const pendingInterview = computed(() =>
  awaitingInput.value && current.value
    ? parsePendingInterview(current.value.id, activeStep.value ?? null)
    : null,
)
const issueUrl = computed(() =>
  current.value
    ? `https://github.com/${current.value.repo}/issues/${current.value.issue_number}`
    : '',
)

// Prose deliverables (refined issue, plan) are markdown — render them as
// HTML. A structured deliverable (a questionnaire envelope) parses as JSON,
// so we never feed it to the markdown renderer; those fall back to the raw
// <pre> view (and, while awaiting input, to the questionnaire form).
const deliverableHtml = computed(() => {
  const text = activeStep.value?.deliverable
  if (!text || parseQuestionnaire(text)) return null
  return renderMarkdown(text)
})

// Named specialist sessions active right now, shown as activity chips.
const activeSessions = computed(() => current.value?.active_sessions ?? [])
const expandedSession = ref<string | null>(null)
const expandedLabel = computed(
  () =>
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
watch(
  () => current.value?.id,
  () => {
    expandedSession.value = null
    closeSession()
  },
)

// Close the drawer once its session is no longer active (the step
// advanced), keeping the workflow view bounded in height.
watch(activeSessions, (list) => {
  if (
    expandedSession.value &&
    !list.some((s) => s.session_id === expandedSession.value)
  ) {
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
    if (await approve(edited.value || undefined)) edited.value = ''
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
    if (await reject(feedback.value)) feedback.value = ''
  } finally {
    busy.value = null
  }
}
async function onReply(): Promise<void> {
  busy.value = 'reply'
  try {
    if (await reply(answer.value)) answer.value = ''
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
async function onSaveDraft(answers: Record<string, unknown>): Promise<void> {
  try {
    await saveDraft(answers)
  } catch {
    /* draft saves are best-effort; ignore transient failures */
  }
}
async function onDelete(id: string): Promise<void> {
  if (
    !confirm(
      'Abandon this workflow? This permanently deletes its local ' +
        'clone and all associated sessions. Nothing on GitHub is changed.',
    )
  )
    return
  await remove(id)
}
function stepStatus(name: string): string {
  return current.value?.steps.find((s) => s.name === name)?.status ?? 'pending'
}
// Map a step/run status onto a Vuetify theme colour; `undefined` leaves the
// chip in its neutral default (pending / not-yet-reached).
function stepColor(status: string): string | undefined {
  if (status === 'done') return 'success'
  if (status === 'running' || status === 'awaiting_input') return 'primary'
  if (status === 'awaiting_approval') return 'warning'
  if (status === 'failed') return 'error'
  return undefined
}
// Crew-chip badge token → Vuetify colour.
const BADGE_COLOR: Record<string, string | undefined> = {
  user: 'info',
  agent: 'primary',
  warn: 'warning',
  ok: 'success',
  err: 'error',
  sys: undefined,
}
function badgeColor(token: string): string | undefined {
  return BADGE_COLOR[token]
}
</script>

<template>
  <ConsoleShell>
    <template #rail>
      <div class="pa-4">
        <div class="text-overline text-medium-emphasis mb-2">New workflow</div>
        <v-text-field v-model="repo" label="owner/name" class="mb-2" />
        <v-text-field
          v-model.number="issueNumber"
          type="number"
          label="Issue #"
          class="mb-3"
        />
        <v-btn
          block
          color="primary"
          prepend-icon="$rocketLaunchOutline"
          :loading="busy === 'create'"
          @click="onCreate"
        >
          Start workflow
        </v-btn>
      </div>
      <v-divider />
      <div class="d-flex align-center justify-space-between px-4 py-2">
        <span class="text-overline text-medium-emphasis">Runs</span>
        <v-chip size="small" variant="tonal">{{ workflows.length }}</v-chip>
      </div>
      <v-list v-if="workflows.length" nav>
        <v-list-item
          v-for="w in workflows"
          :key="w.id"
          :active="w.id === current?.id"
          :title="`${w.repo}#${w.issue_number}`"
          :subtitle="w.status"
          @click="select(w.id)"
        >
          <template #prepend>
            <v-icon
              v-if="w.status.startsWith('awaiting')"
              icon="$circle"
              color="warning"
              size="x-small"
            />
          </template>
          <template #append>
            <v-btn
              icon="$close"
              size="x-small"
              variant="text"
              title="Abandon workflow"
              aria-label="Abandon workflow"
              @click.stop="onDelete(w.id)"
            />
          </template>
        </v-list-item>
      </v-list>
      <div v-else class="px-4 text-medium-emphasis text-body-2">
        No workflows yet
      </div>
    </template>

    <v-alert
      v-if="error"
      type="error"
      closable
      density="compact"
      class="ma-4 mb-0 stage__banner"
      role="alert"
      @click:close="error = null"
    >
      {{ error }}
    </v-alert>

    <v-alert
      v-if="current?.error"
      type="error"
      density="compact"
      class="ma-4 mb-0 stage__banner"
      role="alert"
    >
      Run failed: {{ current.error }}
    </v-alert>

    <template v-if="current">
      <div class="d-flex align-center justify-space-between ga-4 pa-4 border-b">
        <div class="d-flex align-center ga-2">
          <span class="text-overline text-medium-emphasis">Workflow</span>
          <a
            class="stage__id text-body-1"
            :href="issueUrl"
            target="_blank"
            rel="noopener noreferrer"
          >
            {{ current.repo }}#{{ current.issue_number }}
          </a>
        </div>
        <div class="d-flex ga-2 flex-wrap">
          <v-chip
            v-for="name in STEP_LABELS"
            :key="name"
            size="small"
            label
            :color="stepColor(stepStatus(name))"
            :variant="stepColor(stepStatus(name)) ? 'tonal' : 'outlined'"
          >
            {{ name }}
          </v-chip>
          <v-chip
            size="small"
            label
            :color="current.pr_url ? 'success' : undefined"
            :variant="current.pr_url ? 'tonal' : 'outlined'"
          >
            PR
          </v-chip>
        </div>
      </div>

      <div class="stage__body flex-1-1 pa-4 d-flex flex-column ga-4">
        <div v-if="stepRunning">
          <div class="text-overline text-medium-emphasis mb-2">
            {{ activeStep?.name
            }}<template v-if="activeStep?.backend">
              · {{ activeStep.backend }}</template
            ><template
              v-if="activeStep?.name === 'refine' && activeStep.refine_round"
            >
              · round {{ activeStep.refine_round }}/{{
                current.refine_round_cap
              }}
              (max {{ current.refine_max_rounds }})</template
            >
            · live
          </div>
          <div v-if="activeSessions.length" class="d-flex flex-wrap ga-2">
            <v-chip
              v-for="s in activeSessions"
              :key="s.session_id ?? s.profile_id"
              :color="s.status === 'error' ? 'error' : badgeColor(s.badge)"
              :variant="expandedSession === s.session_id ? 'flat' : 'tonal'"
              :disabled="!s.session_id"
              :title="s.status === 'error' ? (s.error ?? undefined) : undefined"
              @click="toggleSession(s.session_id)"
            >
              <template #prepend>
                <v-progress-circular
                  v-if="s.status === 'running'"
                  indeterminate
                  size="12"
                  width="2"
                  class="me-2"
                />
                <v-icon
                  v-else-if="s.status === 'error'"
                  icon="$alertCircle"
                  size="small"
                  class="me-1"
                />
              </template>
              {{ s.label }}
              <span
                v-if="s.status === 'error' && s.error"
                class="ms-1 text-truncate chip__activity"
              >
                · {{ s.error }}
              </span>
              <span
                v-else-if="s.activity"
                class="ms-1 text-truncate chip__activity text-medium-emphasis"
              >
                · {{ s.activity }}
              </span>
            </v-chip>
          </div>
          <v-alert v-else type="info" density="compact" variant="tonal">
            <template #prepend>
              <v-progress-circular indeterminate size="16" width="2" />
            </template>
            {{ activeStep?.name }} — agent is working…
          </v-alert>
        </div>

        <v-alert
          v-if="awaitingInput || awaitingApproval"
          type="warning"
          density="compact"
          variant="tonal"
          role="status"
        >
          {{ activeStep?.name }} —
          {{
            awaitingInput
              ? 'the agent awaits your answers below'
              : 'awaiting your approval below'
          }}
        </v-alert>

        <!-- Only prose deliverables (refined issue, plan, a plain agent
               question) are shown here. A structured deliverable — the
               questionnaire envelope — is JSON, so deliverableHtml is null and
               the block is hidden: the form renders it while awaiting input,
               and nothing dumps the raw JSON during the next run. -->
        <div v-if="deliverableHtml">
          <div class="text-overline text-medium-emphasis mb-1">
            {{
              awaitingInput
                ? `${activeStep?.name} — agent asks`
                : `${activeStep?.name} deliverable`
            }}
          </div>
          <div class="markdown deliverable__prose" v-html="deliverableHtml" />
        </div>

        <div v-if="awaitingApproval" class="d-flex flex-column ga-3">
          <v-textarea
            v-model="edited"
            rows="4"
            :label="`Optionally edit the ${activeStep?.name} deliverable before approving…`"
          />
          <div class="d-flex ga-3">
            <v-btn
              color="primary"
              :loading="busy === 'approve'"
              @click="onApprove"
            >
              Approve
            </v-btn>
            <v-btn
              variant="tonal"
              :loading="busy === 'reject'"
              @click="onReject"
            >
              Reject
            </v-btn>
          </div>
          <v-textarea
            v-model="feedback"
            rows="3"
            label="Or describe what to change and send it back…"
          />
          <v-btn
            variant="outlined"
            :disabled="!feedback.trim()"
            :loading="busy === 'changes'"
            @click="onRequestChanges"
          >
            Request changes
          </v-btn>
        </div>

        <div v-if="awaitingInput">
          <QuestionnaireForm
            v-if="pendingInterview"
            :questionnaire="pendingInterview.questionnaire"
            :draft-answers="pendingInterview.draft_answers"
            :round="pendingInterview.round"
            :allow-incomplete="current?.allow_incomplete_answers ?? false"
            @submit="onSubmitAnswers"
            @save-draft="onSaveDraft"
          />
          <div v-else class="d-flex flex-column ga-3">
            <v-textarea
              v-model="answer"
              rows="3"
              label="Answer the agent's questions…"
            />
            <v-btn color="primary" :loading="busy === 'reply'" @click="onReply">
              Send reply
            </v-btn>
          </div>
        </div>

        <v-btn
          v-if="current.pr_url"
          :href="current.pr_url"
          target="_blank"
          rel="noopener noreferrer"
          variant="text"
          color="primary"
          append-icon="$arrowRight"
        >
          View pull request
        </v-btn>

        <v-card v-if="expandedSession" variant="tonal">
          <v-card-title class="d-flex align-center justify-space-between py-2">
            <span class="text-overline">Session · {{ expandedLabel }}</span>
            <v-btn
              size="small"
              variant="text"
              append-icon="$close"
              @click="toggleSession(expandedSession)"
            >
              Hide
            </v-btn>
          </v-card-title>
          <v-divider />
          <div class="drawer__feed px-3 pb-3">
            <EventCard
              v-for="(e, i) in events"
              :key="i"
              :event="toViewModel(e)"
            />
            <p v-if="!events.length" class="text-medium-emphasis text-body-2">
              Waiting for activity…
            </p>
          </div>
        </v-card>
      </div>
    </template>

    <v-empty-state
      v-else
      headline="No workflow selected"
      text="Start one from an issue on the left."
    />
  </ConsoleShell>
</template>

<style scoped>
/* The prose deliverable is capped to a comfortable reading measure; the
   .markdown element styling itself lives globally in styles/theme.css since
   scoped rules cannot reach v-html children. */
.deliverable__prose {
  max-width: 44rem;
}
.stage__id {
  color: rgb(var(--v-theme-primary));
  text-decoration: none;
}
.stage__body {
  overflow-y: auto;
}
/* v-alert defaults to `flex: 1 1 auto`, so as a child of the flex-column
   stage it both grows to fill empty space and (because its overflow is
   hidden, collapsing its auto min-height) shrinks to a sliver under a tall
   sibling. Pin banners and body children to their natural height; only the
   body itself (flex-1-1) grows and scrolls. `auto` basis is essential —
   the flex-grow-0/flex-shrink-0 utilities set a 0% basis, which re-collapses
   the alert. */
.stage__banner,
.stage__body > * {
  flex: 0 0 auto;
}
/* Keep the on-demand telemetry drawer bounded so the raw event stream can
   never push the panel around. */
.drawer__feed {
  max-height: 300px;
  overflow-y: auto;
}
/* An error/activity hint on a crew chip can be long: keep the chip compact. */
.chip__activity {
  max-width: 22ch;
}
</style>

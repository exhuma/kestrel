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
import DiffView from './DiffView.vue'
import { STEPS } from '../types/workflows'
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

// The canonical steps come from the shared type (mirrors the backend Step
// enum), so the chip row and the domain agree on the vocabulary.
const STEP_LABELS = STEPS

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
// A terminal/failed run must never show a step activity indicator, even if a
// step's status was left 'running' by some backend path — the run-level state
// is authoritative here.
const runFailed = computed(
  () =>
    !!current.value?.error ||
    ['failed', 'escalated', 'rejected'].includes(current.value?.status ?? ''),
)
const stepRunning = computed(
  () => activeStep.value?.status === 'running' && !runFailed.value,
)
const pendingInterview = computed(() =>
  awaitingInput.value && current.value
    ? parsePendingInterview(current.value.id, activeStep.value ?? null)
    : null,
)
// A GitHub issue URL only when the run has a numeric issue (GitHub-sourced);
// a Jira run's ticket lives elsewhere and its ref stays internal (FR-026), so
// there is no deep link from here.
const issueUrl = computed(() =>
  current.value && current.value.issue_number != null
    ? `https://github.com/${current.value.repo}/issues/${current.value.issue_number}`
    : '',
)
// Ticket label for the header: `repo#123` for GitHub, just `repo` for Jira.
const ticketLabel = computed(() =>
  current.value
    ? current.value.issue_number != null
      ? `${current.value.repo}#${current.value.issue_number}`
      : current.value.repo
    : '',
)

// Prose deliverables (refined issue, plan) are markdown — render them as
// HTML. A structured deliverable (a questionnaire envelope) parses as JSON,
// so we never feed it to the markdown renderer; those fall back to the raw
// <pre> view (and, while awaiting input, to the questionnaire form).
const deliverableHtml = computed(() => {
  const step = activeStep.value
  const text = step?.deliverable
  // A diff renders in DiffView, not the markdown path (see isDiffDeliverable).
  if (!text || step?.deliverable_format === 'diff' || parseQuestionnaire(text))
    return null
  return renderMarkdown(text)
})
// The code step's deliverable is a raw git diff: render it in a real diff
// viewer instead of feeding it through the prose markdown renderer.
const isDiffDeliverable = computed(
  () =>
    activeStep.value?.deliverable_format === 'diff' &&
    !!activeStep.value?.deliverable,
)

// Verify-run budget for the verify chip's progress ring. The ring depletes as
// code↔verify iterations are consumed; the centred number is how many remain.
const verifyStep = computed(() =>
  current.value?.steps.find((s) => s.name === 'verify'),
)
const verifyMax = computed(() => current.value?.verify_max_iterations ?? 0)
const verifyRound = computed(() => verifyStep.value?.verify_round ?? 0)
const showVerifyProgress = computed(
  () =>
    verifyRound.value > 0 &&
    verifyMax.value > 0 &&
    !runFailed.value &&
    !current.value?.pr_url,
)
const verifyRemaining = computed(() =>
  Math.max(verifyMax.value - verifyRound.value, 0),
)
const verifyPercent = computed(() =>
  verifyMax.value ? (verifyRemaining.value / verifyMax.value) * 100 : 0,
)

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
// The active-working step's chip pulses to draw the eye to "where we are now".
// Gates (awaiting_*) don't pulse — they surface via the warning alert — and a
// failed/terminal run never pulses (runFailed is authoritative).
function isStepPulsing(name: string): boolean {
  return stepStatus(name) === 'running' && !runFailed.value
}
// Run statuses that mean "actively working" (transient, mid-pipeline) — used
// to spin an activity indicator in the sidebar. Gate (awaiting_*) and terminal
// (failed/escalated/rejected/PR-open) statuses are deliberately excluded.
const ACTIVE_STATUSES = new Set([
  'pending',
  'cloning',
  'refining',
  'designing',
  'coding',
  'verifying',
  'opening_pr',
])
function isActiveStatus(status: string): boolean {
  return ACTIVE_STATUSES.has(status)
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
          :title="
            w.issue_number != null ? `${w.repo}#${w.issue_number}` : w.repo
          "
          :subtitle="w.status"
          @click="select(w.id)"
        >
          <template #prepend>
            <v-progress-circular
              v-if="isActiveStatus(w.status)"
              indeterminate
              size="12"
              width="2"
              color="primary"
              class="me-1"
            />
            <v-icon
              v-else-if="w.status.startsWith('awaiting')"
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
            v-if="issueUrl"
            class="stage__id text-body-1"
            :href="issueUrl"
            target="_blank"
            rel="noopener noreferrer"
          >
            {{ ticketLabel }}
          </a>
          <span v-else class="stage__id text-body-1">{{ ticketLabel }}</span>
        </div>
        <div class="d-flex ga-2 flex-wrap">
          <v-chip
            v-for="name in STEP_LABELS"
            :key="name"
            size="small"
            label
            :color="stepColor(stepStatus(name))"
            :variant="stepColor(stepStatus(name)) ? 'tonal' : 'outlined'"
            :class="{ 'chip--pulse': isStepPulsing(name) }"
          >
            <template v-if="name === 'verify' && showVerifyProgress" #prepend>
              <v-progress-circular
                :model-value="verifyPercent"
                :size="20"
                width="2"
                color="primary"
                class="me-1"
                :title="`verify run ${verifyRound} of ${verifyMax} · ${verifyRemaining} left`"
              >
                <span class="chip__verify-count">{{ verifyRemaining }}</span>
              </v-progress-circular>
            </template>
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
        <div v-if="isDiffDeliverable || deliverableHtml">
          <div class="text-overline text-medium-emphasis mb-1">
            {{
              awaitingInput
                ? `${activeStep?.name} — agent asks`
                : `${activeStep?.name} deliverable`
            }}
          </div>
          <DiffView
            v-if="isDiffDeliverable"
            :diff="activeStep?.deliverable ?? ''"
          />
          <div
            v-else
            class="markdown deliverable__prose"
            v-html="deliverableHtml"
          />
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
/* The running stage's chip pulses to signal live activity. Colours come from
   the Vuetify primary theme token (no hex), so it tracks light/dark. */
.chip--pulse {
  animation: chip-pulse 1.4s ease-in-out infinite;
}
@keyframes chip-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(var(--v-theme-primary), 0.5);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(var(--v-theme-primary), 0);
  }
}
/* Respect users who prefer reduced motion: hold a static emphasis instead. */
@media (prefers-reduced-motion: reduce) {
  .chip--pulse {
    animation: none;
    box-shadow: 0 0 0 2px rgba(var(--v-theme-primary), 0.4);
  }
}
/* The remaining-verify-runs count sits inside a 20px progress ring. */
.chip__verify-count {
  font-size: 10px;
  line-height: 1;
  font-weight: 600;
}
</style>

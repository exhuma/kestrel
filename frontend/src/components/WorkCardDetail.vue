<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import { useBoard } from '../composables/useBoard'
import ArtifactText from './common/ArtifactText.vue'
import type {
  BoardArtifactContent,
  CardAction,
  WorkCardSummary,
} from '../types/workflows'

const props = defineProps<{ card: WorkCardSummary }>()

const { applyIntervention, resolveQuarantine } = useBoard()

const artifactContent = ref<BoardArtifactContent | null>(null)
const artifactError = ref<string | null>(null)

async function loadArtifactContent(artifactId: string): Promise<void> {
  artifactContent.value = null
  artifactError.value = null
  try {
    artifactContent.value = await api.get<BoardArtifactContent>(
      `/api/board/artifacts/${artifactId}/content`,
    )
  } catch {
    artifactError.value = 'Could not load artifact content.'
  }
}

watch(
  () => props.card.latest_artifact?.id,
  (artifactId) => {
    if (artifactId) void loadArtifactContent(artifactId)
    else artifactContent.value = null
  },
  { immediate: true },
)

const STATE_LABELS: Record<string, string> = {
  ready: 'Ready',
  claimed: 'Claimed',
  waiting_dependency: 'Waiting on dependency',
  awaiting_human: 'Awaiting your decision',
  review: 'In review',
  quarantined: 'Quarantined',
  done: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

const stateLabel = computed(
  () => STATE_LABELS[props.card.state] ?? props.card.state,
)

const waitingReasonLabel = computed(() =>
  props.card.state === 'quarantined' ? 'Reason' : 'Waiting',
)

const CONFIRM_MESSAGES: Partial<Record<CardAction, string>> = {
  cancel: 'Cancel this card? This cannot be undone.',
  retry: 'Retry this card?',
  reassign: 'Release the current claim and return this card to ready?',
  request_coordinator_review: 'Ask the coordinator to review this card?',
}

async function runAction(
  action: CardAction,
  decision?: string,
  answer?: string,
): Promise<void> {
  const message = CONFIRM_MESSAGES[action]
  if (message && !confirm(message)) return
  await applyIntervention(props.card.id, action, decision, answer)
}

// A `refinement_gate` (`requested_decision: 'answer'`) asks for a
// free-text answer on approval; a `prd_gate` (`approve_prd`) asks for
// rejection feedback. Every other gate kind is a plain approve/reject.
const answerText = ref('')
const requestsAnswer = computed(
  () => props.card.gate?.requested_decision === 'answer',
)
const requestsPrdFeedback = computed(
  () => props.card.gate?.requested_decision === 'approve_prd',
)
const showAnswerField = computed(
  () => requestsAnswer.value || requestsPrdFeedback.value,
)
const canApproveGate = computed(
  () => !requestsAnswer.value || answerText.value.trim().length > 0,
)
const canRejectGate = computed(
  () => !requestsPrdFeedback.value || answerText.value.trim().length > 0,
)

const canResolveQuarantine = computed(
  () =>
    props.card.state === 'quarantined' &&
    props.card.security_review_id !== null,
)

async function runQuarantineAction(
  action: 'release_quarantine' | 'discard_quarantine',
  message: string,
): Promise<void> {
  const reviewId = props.card.security_review_id
  if (!reviewId || !confirm(message)) return
  await resolveQuarantine(reviewId, action)
}

const ACTION_LABELS: Record<CardAction, string> = {
  retry: 'Retry',
  cancel: 'Cancel',
  reassign: 'Reassign',
  resolve_gate: 'Resolve',
  request_coordinator_review: 'Request coordinator review',
  complete_manual_task: 'Mark done',
}

const nonGateActions = computed(() =>
  props.card.allowed_actions.filter((a) => a !== 'resolve_gate'),
)
const canResolveGate = computed(() =>
  props.card.allowed_actions.includes('resolve_gate'),
)
</script>

<template>
  <v-card
    variant="flat"
    role="region"
    :aria-label="`Card detail: ${card.title}`"
  >
    <v-card-title class="text-wrap">{{ card.title }}</v-card-title>
    <v-card-subtitle>{{ card.card_type }}</v-card-subtitle>

    <v-card-text>
      <v-chip size="small" class="mb-2" data-testid="card-state">{{
        stateLabel
      }}</v-chip>

      <div v-if="card.waiting_reason" class="mb-2 text-body-2">
        {{ waitingReasonLabel }}: {{ card.waiting_reason }}
      </div>

      <div v-if="card.owner" class="mb-1 text-body-2">
        Owner: {{ card.owner.label }}
      </div>
      <div v-if="card.lease" class="mb-1 text-body-2">
        Lease expires: {{ card.lease.expires_at }} (attempt
        {{ card.lease.attempt }})
      </div>

      <div class="mb-1 text-body-2">
        Eligible roles:
        <span v-if="card.eligible_roles.length === 0">none</span>
        <v-chip
          v-for="role in card.eligible_roles"
          :key="role.id"
          size="x-small"
          class="ms-1"
          >{{ role.label }}</v-chip
        >
      </div>

      <div class="mb-1 text-body-2">
        Dependencies: {{ card.dependency_count }}
      </div>

      <div v-if="card.latest_artifact" class="mb-1 text-body-2">
        Latest artifact: {{ card.latest_artifact.label }} (rev
        {{ card.latest_artifact.revision }})
      </div>
      <div v-if="artifactContent" class="mb-2">
        <v-chip size="x-small" class="mb-1" data-testid="artifact-trust">
          {{ artifactContent.trust }}
        </v-chip>
        <ArtifactText
          :text="artifactContent.content"
          :mime-type="artifactContent.mime_type"
        />
      </div>
      <div v-else-if="artifactError" class="mb-2 text-body-2 text-error">
        {{ artifactError }}
      </div>

      <v-textarea
        v-if="canResolveGate && showAnswerField"
        v-model="answerText"
        :label="requestsAnswer ? 'Your answer' : 'Rejection feedback'"
        density="compact"
        rows="3"
        auto-grow
      />
    </v-card-text>

    <v-card-actions
      v-if="card.allowed_actions.length > 0 || canResolveQuarantine"
    >
      <v-btn
        v-for="action in nonGateActions"
        :key="action"
        size="small"
        variant="tonal"
        @click="runAction(action)"
      >
        {{ ACTION_LABELS[action] }}
      </v-btn>
      <template v-if="canResolveGate">
        <v-btn
          size="small"
          color="success"
          variant="tonal"
          :disabled="!canApproveGate"
          @click="
            runAction('resolve_gate', 'approved', answerText || undefined)
          "
        >
          Approve
        </v-btn>
        <v-btn
          size="small"
          color="error"
          variant="tonal"
          :disabled="!canRejectGate"
          @click="
            runAction('resolve_gate', 'rejected', answerText || undefined)
          "
        >
          Reject
        </v-btn>
      </template>
      <template v-if="canResolveQuarantine">
        <v-btn
          size="small"
          color="success"
          variant="tonal"
          @click="
            runQuarantineAction(
              'release_quarantine',
              'Release this content from quarantine? It will be treated as trusted.',
            )
          "
        >
          Release
        </v-btn>
        <v-btn
          size="small"
          color="error"
          variant="tonal"
          @click="
            runQuarantineAction(
              'discard_quarantine',
              'Discard this quarantined content? This cannot be undone.',
            )
          "
        >
          Discard
        </v-btn>
      </template>
    </v-card-actions>
  </v-card>
</template>

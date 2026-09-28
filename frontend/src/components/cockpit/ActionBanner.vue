<script setup lang="ts">
// The single most important element on the page: what does this request
// want from me? (FR-016.)
//
// Renders nothing at all when nothing is pending — not an empty or
// disabled prompt. Answer-shaped work leaves for the interview surface
// (FR-017); only decisions are taken here, and each one is confirmed in a
// `v-dialog` rather than `window.confirm()` (FR-038).
import { computed, ref } from 'vue'
import { pendingAsk, pendingAsks, type PendingAsk } from '../../lib/asks'
import { useBoard } from '../../composables/useBoard'
import type { WorkCardSummary } from '../../types/workflows'
import ArtifactDialog from './ArtifactDialog.vue'

const props = defineProps<{
  cards: WorkCardSummary[]
  /** The workflow, so the interview CTA can address it. */
  workflowId: string
}>()

const { applyIntervention, resolveQuarantine, error } = useBoard()

const ask = computed(() => pendingAsk(props.cards))
const otherAskCount = computed(() =>
  Math.max(pendingAsks(props.cards).length - 1, 0),
)

const tone = computed(() =>
  ask.value?.kind === 'quarantine' ? 'error' : 'warning',
)

/** CAB-2's executive summary is the gate card's own artifact (feature
 *  030), so the operator can read what they are deciding on before
 *  approving. `null` for any other ask, and for a CAB-2 gate opened
 *  before summaries existed. */
const summaryId = computed(() =>
  ask.value?.card.gate?.requested_decision === 'approve_decomposition'
    ? (ask.value.card.latest_artifact?.id ?? null)
    : null,
)
const summaryOpen = ref(false)

/** The confirmation in flight, or `null` when no dialog is open. */
type Confirmation = {
  label: string
  prompt: string
  needsFeedback: boolean
  run: (feedback: string) => Promise<void>
}
const confirming = ref<Confirmation | null>(null)
const feedback = ref('')
const busy = ref(false)

const canSubmit = computed(
  () => !confirming.value?.needsFeedback || feedback.value.trim().length > 0,
)

function confirm(c: Confirmation): void {
  feedback.value = ''
  confirming.value = c
}

async function submit(): Promise<void> {
  const c = confirming.value
  if (!c || !canSubmit.value) return
  busy.value = true
  try {
    await c.run(feedback.value.trim())
  } finally {
    busy.value = false
    confirming.value = null
  }
}

function approve(a: PendingAsk): void {
  confirm({
    label: 'Approve',
    prompt: `${a.title} — approve and let the request continue?`,
    needsFeedback: false,
    run: async () => {
      await applyIntervention(a.card.id, 'resolve_gate', 'approved')
    },
  })
}

function reject(a: PendingAsk): void {
  confirm({
    label: 'Reject',
    prompt: a.requiresRejectionFeedback
      ? 'Say what is wrong with it — the redraft works from this.'
      : `${a.title} — reject it?`,
    needsFeedback: a.requiresRejectionFeedback,
    run: async (text) => {
      await applyIntervention(
        a.card.id,
        'resolve_gate',
        'rejected',
        text || undefined,
      )
    },
  })
}

function release(a: PendingAsk): void {
  confirm({
    label: 'Release',
    prompt:
      'Release this content from quarantine? It will be treated as trusted.',
    needsFeedback: false,
    run: async () => {
      const id = a.card.security_review_id
      if (id) await resolveQuarantine(id, 'release_quarantine')
    },
  })
}

function discard(a: PendingAsk): void {
  confirm({
    label: 'Discard',
    prompt: 'Discard this quarantined content? This cannot be undone.',
    needsFeedback: false,
    run: async () => {
      const id = a.card.security_review_id
      if (id) await resolveQuarantine(id, 'discard_quarantine')
    },
  })
}

/** A 409 means the board moved on under the operator — say that in
 *  words rather than leaving a bare status code on screen (FR-046). */
const staleMessage = computed(() =>
  error.value?.includes('409')
    ? 'This request moved on while you were deciding — the page has newer information now. Take another look before deciding again.'
    : null,
)
</script>

<template>
  <div v-if="ask">
    <v-alert :type="tone" prominent data-testid="action-banner">
      <div class="text-body-1 font-weight-medium">{{ ask.title }}</div>
      <div v-if="otherAskCount > 0" class="text-caption">
        {{ otherAskCount }} other decision(s) also waiting.
      </div>

      <template #append>
        <div class="d-flex ga-2 flex-wrap">
          <v-btn
            v-if="ask.kind === 'interview'"
            color="primary"
            :to="{ name: 'interview', params: { id: workflowId } }"
          >
            Answer the interview
          </v-btn>

          <v-btn
            v-if="summaryId"
            variant="outlined"
            prepend-icon="$textBoxCheckOutline"
            @click="summaryOpen = true"
          >
            Read executive summary
          </v-btn>

          <template v-if="ask.kind === 'approval'">
            <v-btn color="success" variant="tonal" @click="approve(ask)">
              Approve
            </v-btn>
            <v-btn color="error" variant="tonal" @click="reject(ask)">
              Reject
            </v-btn>
          </template>

          <template v-if="ask.kind === 'quarantine'">
            <v-btn color="success" variant="tonal" @click="release(ask)">
              Release
            </v-btn>
            <v-btn color="error" variant="tonal" @click="discard(ask)">
              Discard
            </v-btn>
          </template>
        </div>
      </template>
    </v-alert>

    <v-alert
      v-if="staleMessage"
      type="info"
      class="mt-2"
      data-testid="stale-message"
    >
      {{ staleMessage }}
    </v-alert>

    <ArtifactDialog
      :artifact-id="summaryOpen ? summaryId : null"
      label="Executive summary"
      @close="summaryOpen = false"
    />

    <v-dialog :model-value="confirming !== null" max-width="600" persistent>
      <v-card>
        <v-card-title>{{ confirming?.label }}</v-card-title>
        <v-card-text>
          <p class="mb-3">{{ confirming?.prompt }}</p>
          <v-textarea
            v-if="confirming?.needsFeedback"
            v-model="feedback"
            label="What needs to change"
            rows="4"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="busy" @click="confirming = null">
            Cancel
          </v-btn>
          <v-btn
            color="primary"
            :disabled="!canSubmit"
            :loading="busy"
            @click="submit"
          >
            {{ confirming?.label }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup lang="ts">
// The interview workspace (FR-020): a form shell, distinct from the
// cockpit, that loads the open interview gates' question sets, keeps
// answers in `useInterviewDraft` across round advances, and submits each
// persona's answers through the existing `resolve_gate` path before
// returning to the cockpit by name (FR-020, `contracts/routes.md` §1).
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { useBoard } from '../composables/useBoard'
import { useInterviewDraft } from '../composables/useInterviewDraft'
import NotFoundView from './NotFoundView.vue'
import RoundIndicator from '../components/interview/RoundIndicator.vue'
import PersonaQuestionGroup from '../components/interview/PersonaQuestionGroup.vue'
import {
  buildInterviewCards,
  deriveRoundState,
  isOpenInterviewCard,
} from '../lib/interview'
import {
  allRequiredAnswered,
  outstandingQuestions,
  serializeAnswers,
} from '../lib/interviewAnswers'
import type { BoardArtifactContent, WorkCardSummary } from '../types/workflows'
import type { InterviewCard, QuestionAnswer } from '../types/interview'
import type { DraftStatus } from '../composables/useInterviewDraft'

const route = useRoute()
const router = useRouter()
const {
  current,
  error: boardError,
  loading,
  select,
  stop,
  applyIntervention,
} = useBoard()

const workflowId = computed(() => String(route.params.id ?? ''))
const snapshot = computed(() =>
  current.value?.id === workflowId.value ? current.value : null,
)
const isUnknown = computed(() => boardError.value?.includes('404') === true)
const staleMessage = computed(() =>
  boardError.value?.includes('409')
    ? 'These questions were already answered, perhaps in another tab. The page now shows what is still open.'
    : null,
)

// --- Question set loading (FR-045) --------------------------------------

const openInterviewCards = computed(() =>
  (snapshot.value?.cards ?? []).filter(isOpenInterviewCard),
)
const openIds = computed(() =>
  openInterviewCards.value.map((c) => c.id).join(','),
)
const contentByCardId = ref<Record<string, string | null>>({})
const contentReady = ref(false)

async function fetchContent(
  card: WorkCardSummary,
): Promise<[string, string | null]> {
  // The questions are the gate's target — an artifact of the card that
  // wrote them — never the gate card's own artifact (#66).
  const artifactId = card.gate?.target_artifact?.id
  if (!artifactId) return [card.id, null]
  try {
    const content = await api.get<BoardArtifactContent>(
      `/api/board/artifacts/${artifactId}/content`,
    )
    return [card.id, content.content]
  } catch {
    return [card.id, null]
  }
}

async function loadContent(cards: WorkCardSummary[]): Promise<void> {
  const entries = await Promise.all(cards.map(fetchContent))
  contentByCardId.value = Object.fromEntries(entries)
  contentReady.value = true
}

watch(
  openIds,
  () => {
    contentReady.value = false
    if (!openInterviewCards.value.length) {
      contentByCardId.value = {}
      contentReady.value = true
      return
    }
    void loadContent(openInterviewCards.value)
  },
  { immediate: true },
)

const built = computed(() =>
  contentReady.value
    ? buildInterviewCards(openInterviewCards.value, contentByCardId.value)
    : { cards: [] as InterviewCard[], unreadable: [] as WorkCardSummary[] },
)
const interviewCards = computed(() => built.value.cards)
const unreadable = computed(() => built.value.unreadable)
const roundState = computed(() => deriveRoundState(interviewCards.value))

// --- Draft answers (FR-022, FR-025) --------------------------------------

const draft = computed(() => useInterviewDraft(workflowId.value))
// `draft.value.status` is a nested Ref reached through a computed, which
// the template would not auto-unwrap — expose it as its own top-level
// computed instead, which does.
const draftStatus = computed(() => draft.value.status.value)

// A snackbar is transient by nature: it must be able to dismiss itself
// (timeout or manual close) independently of `draftStatus`, which does
// not revert on its own. Two-way `v-model` on its own ref, set each time
// a save newly completes, rather than binding the snackbar directly to
// `draftStatus` (which a `:model-value`-only binding could never close).
const showSavedSnack = ref(false)
watch(draftStatus, (status) => {
  if (status === 'saved') showSavedSnack.value = true
})

// Only a loaded question set is reconciled against. While one reloads
// (after each persona's submission) there are no questions to match, and
// reconciling then would drop every answer still to be submitted.
watch(interviewCards, (cards) => {
  if (contentReady.value)
    draft.value.reconcile(cards.flatMap((c) => c.questions))
})

function setAnswer(questionId: string, answer: QuestionAnswer): void {
  draft.value.setAnswer(questionId, answer)
}

const allQuestions = computed(() =>
  interviewCards.value.flatMap((c) => c.questions),
)
const canSubmit = computed(() =>
  allRequiredAnswered(allQuestions.value, draft.value.answers),
)
const outstanding = computed(() =>
  outstandingQuestions(allQuestions.value, draft.value.answers),
)

const DRAFT_STATUS_LABEL: Record<DraftStatus, string> = {
  idle: '',
  dirty: 'Unsaved changes…',
  saving: 'Saving…',
  saved: 'Draft saved',
}

// --- Submit (FR-046) ------------------------------------------------------

const submitting = ref(false)
const submitError = ref<string | null>(null)

async function submitCard(cardId: string, answer: string): Promise<boolean> {
  const result = await applyIntervention(
    cardId,
    'resolve_gate',
    'approved',
    answer,
  )
  if (!result) return false
  await select(workflowId.value)
  return true
}

async function submit(): Promise<void> {
  if (!canSubmit.value || submitting.value) return
  submitting.value = true
  submitError.value = null
  // Serialised up front: each submission refreshes the board, and the
  // page must not depend on what it shows mid-way.
  const submissions = interviewCards.value.map(
    (card) =>
      [
        card.cardId,
        serializeAnswers(card.questions, draft.value.answers),
      ] as const,
  )
  try {
    for (const [cardId, answer] of submissions) {
      // Sequential, not Promise.all: each card's revision must be fresh
      // (via the `select` in submitCard) before the next is submitted.
      const ok = await submitCard(cardId, answer)
      if (!ok) {
        submitError.value =
          boardError.value ?? 'Could not submit — please try again.'
        return
      }
    }
    await router.push({ name: 'cockpit', params: { id: workflowId.value } })
  } finally {
    submitting.value = false
  }
}

// --- Lifecycle & the no-open-interview redirect ---------------------------

watch(
  workflowId,
  (id) => {
    if (id) void select(id)
  },
  { immediate: true },
)

// A request with no open interview redirects to its cockpit, which
// states what it is waiting on instead (contracts/routes.md §1).
watch(
  () => [
    snapshot.value !== null,
    contentReady.value,
    interviewCards.value.length,
    unreadable.value.length,
    submitting.value,
  ],
  ([hasSnapshot, ready, openCount, badCount, isSubmitting]) => {
    if (hasSnapshot && ready && !openCount && !badCount && !isSubmitting) {
      void router.replace({ name: 'cockpit', params: { id: workflowId.value } })
    }
  },
  { immediate: true },
)

onUnmounted(() => stop())
</script>

<template>
  <NotFoundView v-if="isUnknown" />

  <div v-else class="interview pa-4">
    <v-alert v-if="boardError && !isUnknown" type="error" class="mb-4">
      {{ boardError }}
    </v-alert>

    <v-progress-linear v-if="loading && !snapshot" indeterminate />

    <template v-if="snapshot">
      <div class="d-flex align-center justify-space-between mb-4">
        <div class="text-h6">{{ snapshot.title }} — interview</div>
        <v-btn
          :to="{ name: 'cockpit', params: { id: workflowId } }"
          variant="text"
        >
          Back to cockpit
        </v-btn>
      </div>

      <RoundIndicator
        class="mb-4"
        :current="roundState.current"
        :cap="roundState.cap"
      />

      <v-alert
        v-if="contentReady && unreadable.length"
        type="warning"
        class="mb-4"
        data-testid="unreadable-alert"
      >
        Could not read {{ unreadable.length }} question set(s) for this
        interview. Try again shortly.
      </v-alert>

      <v-form
        v-if="interviewCards.length"
        class="d-flex flex-column ga-4"
        @submit.prevent="submit"
      >
        <PersonaQuestionGroup
          v-for="card in interviewCards"
          :key="card.cardId"
          :card="card"
          :answers="draft.answers"
          @update:answer="setAnswer"
        />

        <v-alert v-if="submitError" type="error" data-testid="submit-error">
          {{ submitError }}
        </v-alert>
        <v-alert v-if="staleMessage" type="info" data-testid="stale-message">
          {{ staleMessage }}
        </v-alert>

        <div class="d-flex align-center ga-3 flex-wrap">
          <v-btn
            type="submit"
            color="primary"
            :disabled="!canSubmit"
            :loading="submitting"
          >
            Submit answers
          </v-btn>
          <span
            v-if="outstanding.length"
            class="text-caption text-medium-emphasis"
            data-testid="outstanding"
          >
            {{ outstanding.length }} question(s) still need an answer or a
            reason.
          </span>
          <span
            v-else-if="draftStatus !== 'idle'"
            class="text-caption text-medium-emphasis"
            data-testid="draft-status"
          >
            {{ DRAFT_STATUS_LABEL[draftStatus] }}
          </span>
        </div>
      </v-form>

      <!-- Transient confirmation on top of the persistent status caption
           above (FR-022): a draft save and a final submission must never
           read as the same event — the submission instead navigates away
           entirely. -->
      <v-snackbar
        v-model="showSavedSnack"
        timeout="2000"
        location="bottom"
        data-testid="draft-saved-snackbar"
      >
        Draft saved
      </v-snackbar>
    </template>
  </div>
</template>

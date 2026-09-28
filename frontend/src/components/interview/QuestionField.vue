<script setup lang="ts">
// One question with both escape hatches (FR-023): a concrete answer via
// `v-textarea`, or "I don't know" / "not relevant" — mutually exclusive
// with each other and with the textarea, and neither ever recorded as an
// empty answer (the two checkboxes carry `state`, not blank text).
import { computed } from 'vue'
import type { InterviewQuestion, QuestionAnswer } from '../../types/interview'

const props = defineProps<{
  question: InterviewQuestion
  answer: QuestionAnswer | undefined
}>()
const emit = defineEmits<{ 'update:answer': [answer: QuestionAnswer] }>()

const state = computed(() => props.answer?.state ?? 'unanswered')
const text = computed(() =>
  state.value === 'answered' ? (props.answer?.text ?? '') : '',
)
const showText = computed(
  () => state.value !== 'unknown' && state.value !== 'not-relevant',
)

function setText(value: string): void {
  emit('update:answer', {
    state: value.trim() ? 'answered' : 'unanswered',
    text: value,
  })
}
function setUnknown(on: boolean): void {
  emit('update:answer', { state: on ? 'unknown' : 'unanswered', text: '' })
}
function setNotRelevant(on: boolean): void {
  emit('update:answer', {
    state: on ? 'not-relevant' : 'unanswered',
    text: '',
  })
}
</script>

<template>
  <div
    class="pa-3 rounded border"
    role="group"
    :aria-labelledby="`qp-${question.id}`"
  >
    <p :id="`qp-${question.id}`" class="text-body-2 font-weight-medium mb-2">
      {{ question.prompt }}
    </p>

    <v-textarea
      v-if="showText"
      data-testid="answer-text"
      :model-value="text"
      rows="2"
      @update:model-value="setText"
    />

    <div class="d-flex flex-wrap ga-4 mt-1">
      <v-checkbox
        data-testid="toggle-unknown"
        label="I don't know — let the PRD state an assumption"
        :model-value="state === 'unknown'"
        density="compact"
        hide-details
        @update:model-value="setUnknown($event === true)"
      />
      <v-checkbox
        data-testid="toggle-not-relevant"
        label="Not relevant"
        :model-value="state === 'not-relevant'"
        density="compact"
        hide-details
        @update:model-value="setNotRelevant($event === true)"
      />
    </div>
  </div>
</template>

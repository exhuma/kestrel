<script setup lang="ts">
// One question with both escape hatches (FR-023). An open question is
// answered in a `v-textarea`; a choice question (feature 034) by picking
// one option (`v-radio-group`) or several (`v-checkbox`), with an optional
// comment. "I don't know" / "not relevant" stay mutually exclusive with
// each other and with any answer, and neither is ever recorded as an
// empty answer (the two checkboxes carry `state`, not blank text).
import { computed } from 'vue'
import ArtifactText from '../common/ArtifactText.vue'
import type { InterviewQuestion, QuestionAnswer } from '../../types/interview'

const props = defineProps<{
  question: InterviewQuestion
  answer: QuestionAnswer | undefined
}>()
const emit = defineEmits<{ 'update:answer': [answer: QuestionAnswer] }>()

const state = computed(() => props.answer?.state ?? 'unanswered')
const answering = computed(() => state.value === 'answered')
const text = computed(() => (answering.value ? (props.answer?.text ?? '') : ''))
const choices = computed(() =>
  answering.value ? (props.answer?.choices ?? []) : [],
)
const showAnswer = computed(
  () => state.value !== 'unknown' && state.value !== 'not-relevant',
)
const isChoice = computed(() => (props.question.options?.length ?? 0) > 0)

/** Answered as soon as anything is picked or written. */
function record(nextChoices: string[], nextText: string): void {
  const answered = nextChoices.length > 0 || nextText.trim().length > 0
  emit('update:answer', {
    state: answered ? 'answered' : 'unanswered',
    text: nextText,
    ...(isChoice.value ? { choices: nextChoices } : {}),
  })
}

function setText(value: string): void {
  record(choices.value, value)
}
function pickOne(option: string | null): void {
  record(option ? [option] : [], text.value)
}
function toggle(option: string, on: boolean): void {
  const rest = choices.value.filter((c) => c !== option)
  record(on ? [...rest, option] : rest, text.value)
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
    <div :id="`qp-${question.id}`" class="font-weight-medium mb-2">
      <ArtifactText :text="question.prompt" mime-type="text/markdown" />
    </div>

    <template v-if="showAnswer && isChoice">
      <div v-if="question.multiple" data-testid="answer-choices">
        <v-checkbox
          v-for="option in question.options"
          :key="option"
          :label="option"
          :model-value="choices.includes(option)"
          density="compact"
          hide-details
          @update:model-value="toggle(option, $event === true)"
        />
      </div>
      <v-radio-group
        v-else
        data-testid="answer-choices"
        :model-value="choices[0] ?? null"
        density="compact"
        hide-details
        @update:model-value="pickOne($event as string | null)"
      >
        <v-radio
          v-for="option in question.options"
          :key="option"
          :label="option"
          :value="option"
        />
      </v-radio-group>
    </template>

    <v-textarea
      v-if="showAnswer"
      data-testid="answer-text"
      :label="isChoice ? 'Comment (optional)' : undefined"
      :model-value="text"
      :rows="isChoice ? 1 : 2"
      auto-grow
      class="mt-2"
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

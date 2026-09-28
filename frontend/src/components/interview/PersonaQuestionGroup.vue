<script setup lang="ts">
// One persona's questions (FR-021), composing `QuestionField` per
// question. Answers are looked up by id from the shared draft map rather
// than held locally, so a round-advance reconciliation elsewhere is
// immediately visible here.
import type { InterviewCard, QuestionAnswer } from '../../types/interview'
import QuestionField from './QuestionField.vue'

defineProps<{
  card: InterviewCard
  answers: Record<string, QuestionAnswer>
}>()
const emit = defineEmits<{
  'update:answer': [questionId: string, answer: QuestionAnswer]
}>()
</script>

<template>
  <v-card variant="tonal">
    <v-card-title class="text-capitalize">{{ card.persona }}</v-card-title>
    <v-card-text class="d-flex flex-column ga-3">
      <QuestionField
        v-for="q in card.questions"
        :key="q.id"
        :question="q"
        :answer="answers[q.id]"
        @update:answer="emit('update:answer', q.id, $event)"
      />
    </v-card-text>
  </v-card>
</template>

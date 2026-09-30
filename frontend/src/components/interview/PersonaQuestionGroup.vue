<script setup lang="ts">
// One persona's questions (FR-021), composing `QuestionField` per
// question. Answers are looked up by id from the shared draft map rather
// than held locally, so a round-advance reconciliation elsewhere is
// immediately visible here.
//
// Each specialist's form carries a faint tint of its own theme colour
// (feature 039), so the forms of several profiles read apart at a
// glance. The heading names the profile, so the colour is never the
// only signal; a specialist outside the palette stays neutral.
import { computed } from 'vue'
import { specialistColor } from '../../lib/specialistColor'
import type { InterviewCard, QuestionAnswer } from '../../types/interview'
import QuestionField from './QuestionField.vue'

const props = defineProps<{
  card: InterviewCard
  answers: Record<string, QuestionAnswer>
}>()
const emit = defineEmits<{
  'update:answer': [questionId: string, answer: QuestionAnswer]
}>()

const color = computed(() => specialistColor(props.card.persona))
const tint = computed(() =>
  color.value
    ? {
        '--specialist': `var(--v-theme-${color.value})`,
      }
    : undefined,
)
</script>

<template>
  <v-card
    variant="outlined"
    :class="{ 'persona-group--tinted': color }"
    :style="tint"
    :data-specialist="card.persona"
  >
    <v-card-title>{{ card.personaLabel }}</v-card-title>
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

<style scoped>
/* Named custom-CSS gap: Vuetify tints a card only at its fixed tonal
   strength (and recolours its text with it); the interview needs a much
   fainter wash that leaves the text alone. The colour itself is a theme
   colour, never a literal. */
.persona-group--tinted {
  background: rgba(var(--specialist), 0.06);
  border-left: 4px solid rgb(var(--specialist));
}
</style>

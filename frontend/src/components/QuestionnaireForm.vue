<script setup lang="ts">
import { reactive, computed } from 'vue'
import type { Questionnaire } from '../types/questionnaire'
import { allRequiredAnswered } from '../lib/questionnaire'

const props = defineProps<{ questionnaire: Questionnaire }>()
const emit = defineEmits<{ submit: [answers: Record<string, unknown>] }>()

const answers = reactive<Record<string, unknown>>({})

const canSubmit = computed(() =>
  allRequiredAnswered(props.questionnaire, answers),
)

function toggleMulti(id: string, value: string, checked: boolean): void {
  const current = new Set((answers[id] as string[] | undefined) ?? [])
  if (checked) current.add(value)
  else current.delete(value)
  answers[id] = Array.from(current)
}

function onSubmit(): void {
  if (canSubmit.value) emit('submit', { ...answers })
}
</script>

<template>
  <form class="qform" @submit.prevent="onSubmit">
    <fieldset v-for="q in questionnaire.questions" :key="q.id" class="qform__q">
      <legend class="qform__prompt">
        {{ q.prompt }}<span v-if="q.required" aria-hidden="true"> *</span>
      </legend>
      <p v-if="q.why" class="qform__why mono">{{ q.why }}</p>

      <div v-if="q.type === 'single_select'" class="qform__options">
        <label v-for="o in q.options" :key="o.value" class="qform__option">
          <input type="radio" :name="q.id" :value="o.value"
            @change="answers[q.id] = o.value" />
          {{ o.label }}
        </label>
      </div>

      <div v-else-if="q.type === 'multi_select'" class="qform__options">
        <label v-for="o in q.options" :key="o.value" class="qform__option">
          <input type="checkbox" :value="o.value"
            @change="toggleMulti(q.id, o.value, ($event.target as HTMLInputElement).checked)" />
          {{ o.label }}
        </label>
      </div>

      <div v-else-if="q.type === 'boolean'" class="qform__options">
        <label class="qform__option">
          <input type="radio" :name="q.id" @change="answers[q.id] = true" />
          Yes
        </label>
        <label class="qform__option">
          <input type="radio" :name="q.id" @change="answers[q.id] = false" />
          No
        </label>
      </div>

      <textarea v-else class="field" rows="2"
        @input="answers[q.id] = ($event.target as HTMLTextAreaElement).value" />
    </fieldset>

    <button type="submit" class="btn btn--primary" :disabled="!canSubmit">
      Submit answers
    </button>
  </form>
</template>

<style scoped>
.qform { display: flex; flex-direction: column; gap: 16px; }
.qform__q { border: 1px solid var(--line); border-radius: var(--r-md);
  padding: 12px 14px; }
.qform__prompt { font-size: 13px; color: var(--text-hi); padding: 0 4px; }
.qform__why { font-size: 11.5px; color: var(--text-dim); margin: 4px 0 10px; }
.qform__options { display: flex; flex-direction: column; gap: 6px; }
.qform__option { display: flex; align-items: center; gap: 8px;
  font-size: 12.5px; color: var(--text-mid); }
</style>

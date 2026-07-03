<script setup lang="ts">
import { reactive, computed, watch } from 'vue'
import type { Questionnaire, WaiverAnswer } from '../types/questionnaire'
import { allRequiredAnswered, groupByProfile, isWaiver } from '../lib/questionnaire'

const props = defineProps<{
  questionnaire: Questionnaire
  draftAnswers?: Record<string, unknown>
}>()
const emit = defineEmits<{
  submit: [answers: Record<string, unknown>]
  saveDraft: [answers: Record<string, unknown>]
}>()

const answers = reactive<Record<string, unknown>>({ ...(props.draftAnswers ?? {}) })

// A new round replaces the questionnaire in place; reseed the draft.
watch(
  () => props.questionnaire,
  () => {
    for (const key of Object.keys(answers)) delete answers[key]
    Object.assign(answers, props.draftAnswers ?? {})
  },
)

const groups = computed(() => groupByProfile(props.questionnaire, answers))
const canSubmit = computed(() =>
  allRequiredAnswered(props.questionnaire, answers),
)

const BADGE: Record<string, string> = {
  user: 'var(--user)', agent: 'var(--signal)', warn: 'var(--warn)',
  ok: 'var(--ok)', err: 'var(--err)', sys: 'var(--idle)',
}
const badgeColor = (token: string): string => BADGE[token] ?? 'var(--idle)'

function waived(id: string): boolean {
  return isWaiver(answers[id])
}
function reasonOf(id: string): string {
  const v = answers[id]
  return isWaiver(v) ? v.reason : ''
}
function toggleWaiver(id: string, on: boolean): void {
  answers[id] = on ? ({ waived: true, reason: '' } as WaiverAnswer) : undefined
}
function setReason(id: string, reason: string): void {
  answers[id] = { waived: true, reason } as WaiverAnswer
}
function toggleMulti(id: string, value: string, checked: boolean): void {
  const current = new Set(
    Array.isArray(answers[id]) ? (answers[id] as string[]) : [],
  )
  if (checked) current.add(value)
  else current.delete(value)
  answers[id] = Array.from(current)
}
function isChecked(id: string, value: string): boolean {
  return Array.isArray(answers[id]) && (answers[id] as string[]).includes(value)
}

function onSubmit(): void {
  if (canSubmit.value) emit('submit', { ...answers })
}
function onSaveDraft(): void {
  emit('saveDraft', { ...answers })
}
</script>

<template>
  <form class="qform" @submit.prevent="onSubmit">
    <section v-for="g in groups" :key="g.profile.id" class="qgroup">
      <header class="qgroup__head">
        <span class="qbadge" :style="{ '--c': badgeColor(g.profile.badge) }">
          {{ g.profile.label }}
        </span>
        <span class="qgroup__progress mono">
          {{ g.answered }}/{{ g.questions.length }} answered
        </span>
      </header>

      <fieldset
        v-for="q in g.questions"
        :key="q.id"
        class="qform__q"
        :class="{ 'qform__q--waived': waived(q.id) }"
      >
        <legend class="qform__prompt">
          {{ q.prompt }}<span v-if="q.required" aria-hidden="true"> *</span>
        </legend>
        <p v-if="q.why" class="qform__why mono">{{ q.why }}</p>

        <template v-if="!waived(q.id)">
          <div v-if="q.type === 'single_select'" class="qform__options">
            <label v-for="o in q.options" :key="o.value" class="qform__option">
              <input type="radio" :name="q.id" :value="o.value"
                :checked="answers[q.id] === o.value"
                @change="answers[q.id] = o.value" />
              {{ o.label }}
            </label>
          </div>

          <div v-else-if="q.type === 'multi_select'" class="qform__options">
            <label v-for="o in q.options" :key="o.value" class="qform__option">
              <input type="checkbox" :value="o.value"
                :checked="isChecked(q.id, o.value)"
                @change="toggleMulti(q.id, o.value, ($event.target as HTMLInputElement).checked)" />
              {{ o.label }}
            </label>
          </div>

          <div v-else-if="q.type === 'boolean'" class="qform__options">
            <label class="qform__option">
              <input type="radio" :name="q.id" :checked="answers[q.id] === true"
                @change="answers[q.id] = true" />
              Yes
            </label>
            <label class="qform__option">
              <input type="radio" :name="q.id" :checked="answers[q.id] === false"
                @change="answers[q.id] = false" />
              No
            </label>
          </div>

          <textarea v-else class="field" rows="2"
            :value="typeof answers[q.id] === 'string' ? (answers[q.id] as string) : ''"
            @input="answers[q.id] = ($event.target as HTMLTextAreaElement).value" />
        </template>

        <div v-else class="qform__waiver">
          <textarea class="field" rows="2"
            :value="reasonOf(q.id)"
            :placeholder="`Reason (required) — recorded in the refined issue…`"
            @input="setReason(q.id, ($event.target as HTMLTextAreaElement).value)" />
        </div>

        <label class="qform__waivetoggle">
          <input type="checkbox" :checked="waived(q.id)"
            @change="toggleWaiver(q.id, ($event.target as HTMLInputElement).checked)" />
          {{ q.waiver_label || 'Unknown / N/A' }} — give a reason
        </label>
      </fieldset>
    </section>

    <div class="qform__actions">
      <button type="submit" class="btn btn--primary" :disabled="!canSubmit">
        Submit answers
      </button>
      <button type="button" class="btn btn--ghost" @click="onSaveDraft">
        Save progress
      </button>
    </div>
  </form>
</template>

<style scoped>
.qform { display: flex; flex-direction: column; gap: 18px; }
.qgroup { display: flex; flex-direction: column; gap: 10px; }
.qgroup__head { display: flex; align-items: center; justify-content: space-between; }
.qbadge {
  --c: var(--idle); font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.06em; font-weight: 600; padding: 2px 10px;
  border-radius: 999px; color: var(--ink-900);
  background: var(--c);
}
.qgroup__progress { font-size: 11px; color: var(--text-dim); }
.qform__q { border: 1px solid var(--line); border-radius: var(--r-md);
  padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.qform__q--waived { border-style: dashed; border-color: var(--warn); }
.qform__prompt { font-size: 13px; color: var(--text-hi); padding: 0 4px; }
.qform__why { font-size: 11.5px; color: var(--text-dim); margin: 4px 0 0; }
.qform__options { display: flex; flex-direction: column; gap: 6px; }
.qform__option { display: flex; align-items: center; gap: 8px;
  font-size: 12.5px; color: var(--text-mid); }
.qform__waivetoggle { display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--warn); margin-top: 2px; }
.qform__actions { display: flex; gap: 10px; }
.qform__actions .btn { width: auto; padding-left: 22px; padding-right: 22px; }
</style>

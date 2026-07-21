<script setup lang="ts">
import { reactive, computed, ref, watch } from 'vue'
import type {
  CustomAnswer,
  Questionnaire,
  WaiverAnswer,
} from '../types/questionnaire'
import type { ProfileGroup } from '../lib/questionnaire'
import {
  allRequiredAnswered,
  groupByProfile,
  isAnswered,
  isCustom,
  isWaiver,
  noteOf,
  primaryValue,
} from '../lib/questionnaire'
import { debounce } from '../lib/debounce'

const props = defineProps<{
  questionnaire: Questionnaire
  draftAnswers?: Record<string, unknown>
  round: number
  /** Safety net: allow submitting with required questions unanswered. */
  allowIncomplete?: boolean
}>()
const emit = defineEmits<{
  submit: [answers: Record<string, unknown>]
  saveDraft: [answers: Record<string, unknown>]
}>()

const answers = reactive<Record<string, unknown>>({
  ...(props.draftAnswers ?? {}),
})
const saveStatus = ref<'idle' | 'dirty' | 'saving' | 'saved'>('idle')
const justAdvanced = ref(false)

// The round counter only advances on a genuine questionnaire change
// (bumped server-side, never on a draft save) — unlike the previous
// reference-identity watch on `questionnaire`, this never fires on an
// SSE tick that carries no real change, so in-progress answers are
// never spuriously cleared. On a genuine change, keep local answers
// for any question id that still exists and drop only the rest.
watch(
  () => props.round,
  () => {
    const validIds = new Set(props.questionnaire.questions.map((q) => q.id))
    const merged: Record<string, unknown> = {}
    for (const [id, value] of Object.entries(answers)) {
      if (validIds.has(id)) merged[id] = value
    }
    for (const [id, value] of Object.entries(props.draftAnswers ?? {})) {
      if (validIds.has(id) && !(id in merged)) merged[id] = value
    }
    for (const key of Object.keys(answers)) delete answers[key]
    Object.assign(answers, merged)
    justAdvanced.value = true
    setTimeout(() => {
      justAdvanced.value = false
    }, 4000)
  },
)

async function flushSave(): Promise<void> {
  saveStatus.value = 'saving'
  emit('saveDraft', { ...answers })
  saveStatus.value = 'saved'
}
const debouncedSave = debounce(flushSave, 1200)

// Auto-save on any answer change, debounced so rapid keystrokes
// coalesce into one draft write rather than one per keystroke.
watch(
  answers,
  () => {
    saveStatus.value = 'dirty'
    debouncedSave()
  },
  { deep: true },
)

const SAVE_STATUS_LABEL: Record<typeof saveStatus.value, string> = {
  idle: '',
  dirty: 'Unsaved changes…',
  saving: 'Saving…',
  saved: 'Answers saved',
}
const saveStatusLabel = computed(() => SAVE_STATUS_LABEL[saveStatus.value])

const groups = computed(() => groupByProfile(props.questionnaire, answers))
// Specialists that failed to respond this round (crash/timeout/empty),
// stamped by the backend; surfaced here so the failure survives after the
// live chips clear at this gate. Soft failures are retried when the user
// submits; hard failures have exhausted their retry budget.
const issues = computed(() => props.questionnaire.issues ?? [])
const softIssues = computed(() =>
  issues.value.filter((i) => i.severity === 'soft'),
)
const hardIssues = computed(() =>
  issues.value.filter((i) => i.severity === 'hard'),
)
const complete = computed(() =>
  allRequiredAnswered(props.questionnaire, answers),
)
// The safety net lets an incomplete questionnaire go through (unanswered
// questions are sent blank); it never blocks a complete one.
const canSubmit = computed(() => complete.value || !!props.allowIncomplete)
const submittingIncomplete = computed(() => canSubmit.value && !complete.value)

// One tab per specialist; the tab reuses the same mnemonic + badge as
// the session chip. Keep the active tab valid as rounds change.
const activeTab = ref<string | null>(null)
watch(
  groups,
  (gs) => {
    if (!gs.some((g) => g.profile.id === activeTab.value)) {
      activeTab.value = gs[0]?.profile.id ?? null
    }
  },
  { immediate: true },
)

/** True once every required question in a group is answered or waived. */
function groupComplete(g: ProfileGroup): boolean {
  return g.questions
    .filter((q) => q.required)
    .every((q) => isAnswered(q, answers))
}

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

// "None of these fit" correction — mutually exclusive with the waiver
// and any concrete answer, since each helper overwrites answers[id].
function custom(id: string): boolean {
  return isCustom(answers[id])
}
function customTextOf(id: string): string {
  const v = answers[id]
  return isCustom(v) ? v.custom : ''
}
function toggleCustom(id: string, on: boolean): void {
  answers[id] = on ? ({ custom: '' } as CustomAnswer) : undefined
}
function setCustom(id: string, text: string): void {
  answers[id] = { custom: text } as CustomAnswer
}

// A concrete answer may carry an optional "additional information" note.
// Reads/writes go through these so a note and its answer stay paired.
function primary(id: string): unknown {
  return primaryValue(id, answers)
}
function noteFor(id: string): string {
  return noteOf(id, answers)
}
function setPrimary(id: string, value: unknown): void {
  const note = noteOf(id, answers)
  answers[id] = note ? { value, note } : value
}
function setNote(id: string, text: string): void {
  const value = primaryValue(id, answers)
  if (!text) answers[id] = value
  else answers[id] = { value: value ?? null, note: text }
}
function toggleMulti(id: string, value: string, checked: boolean): void {
  const cur = primary(id)
  const current = new Set(Array.isArray(cur) ? (cur as string[]) : [])
  if (checked) current.add(value)
  else current.delete(value)
  setPrimary(id, Array.from(current))
}
function isChecked(id: string, value: string): boolean {
  const cur = primary(id)
  return Array.isArray(cur) && (cur as string[]).includes(value)
}

function onSubmit(): void {
  if (canSubmit.value) emit('submit', { ...answers })
}
function onSaveDraft(): void {
  void flushSave()
}
</script>

<template>
  <v-form class="qform d-flex flex-column ga-4" @submit.prevent="onSubmit">
    <v-alert
      v-if="justAdvanced"
      type="info"
      density="compact"
      role="status"
      text="New questions arrived — your answers were kept."
    />

    <v-alert
      v-if="softIssues.length"
      data-testid="issues-soft"
      type="warning"
      density="compact"
      role="status"
    >
      <p class="mb-1">
        {{ softIssues.length }}
        specialist{{ softIssues.length > 1 ? 's' : '' }} didn't respond and will
        be retried when you submit your answers:
      </p>
      <ul class="ps-4 mb-0">
        <li v-for="i in softIssues" :key="i.profile">
          <strong>{{ i.label }}</strong> — {{ i.reason }}
        </li>
      </ul>
    </v-alert>

    <v-alert
      v-if="hardIssues.length"
      data-testid="issues-hard"
      type="error"
      density="compact"
      role="alert"
    >
      <p class="mb-1">
        {{ hardIssues.length }}
        specialist{{ hardIssues.length > 1 ? 's' : '' }} failed after 3 retries
        and {{ hardIssues.length > 1 ? 'were' : 'was' }} skipped:
      </p>
      <ul class="ps-4 mb-0">
        <li v-for="i in hardIssues" :key="i.profile">
          <strong>{{ i.label }}</strong> — {{ i.reason }}
        </li>
      </ul>
    </v-alert>

    <v-tabs
      v-if="groups.length > 1"
      v-model="activeTab"
      density="compact"
      show-arrows
    >
      <v-tab v-for="g in groups" :key="g.profile.id" :value="g.profile.id">
        {{ g.profile.label }}
        <v-chip
          class="ms-2"
          size="x-small"
          :color="groupComplete(g) ? 'success' : undefined"
        >
          {{ g.answered }}/{{ g.questions.length }}
        </v-chip>
      </v-tab>
    </v-tabs>

    <section
      v-for="g in groups"
      v-show="activeTab === g.profile.id"
      :key="g.profile.id"
      class="d-flex flex-column ga-3"
    >
      <div
        v-if="groups.length === 1"
        class="d-flex align-center justify-space-between"
      >
        <v-chip label size="small" color="primary" variant="tonal">
          {{ g.profile.label }}
        </v-chip>
        <span class="text-caption text-medium-emphasis">
          {{ g.answered }}/{{ g.questions.length }} answered
        </span>
      </div>

      <div
        v-for="q in g.questions"
        :key="q.id"
        data-testid="qblock"
        class="pa-3 rounded border"
        role="group"
        :aria-labelledby="`qp-${q.id}`"
      >
        <p :id="`qp-${q.id}`" class="text-body-2 font-weight-medium mb-1">
          {{ q.prompt }}<span v-if="q.required" aria-hidden="true"> *</span>
        </p>
        <p v-if="q.why" class="text-caption text-medium-emphasis mb-2">
          {{ q.why }}
        </p>

        <template v-if="!waived(q.id) && !custom(q.id)">
          <v-radio-group
            v-if="q.type === 'single_select'"
            :model-value="primary(q.id)"
            hide-details
            @update:model-value="setPrimary(q.id, $event)"
          >
            <v-radio
              v-for="o in q.options"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </v-radio-group>

          <template v-else-if="q.type === 'multi_select'">
            <v-checkbox
              v-for="o in q.options"
              :key="o.value"
              :label="o.label"
              :model-value="isChecked(q.id, o.value)"
              density="compact"
              hide-details
              @update:model-value="toggleMulti(q.id, o.value, $event === true)"
            />
          </template>

          <v-radio-group
            v-else-if="q.type === 'boolean'"
            :model-value="primary(q.id)"
            hide-details
            @update:model-value="setPrimary(q.id, $event)"
          >
            <v-radio label="Yes" :value="true" />
            <v-radio label="No" :value="false" />
          </v-radio-group>

          <v-textarea
            v-else
            data-testid="primary-text"
            :model-value="
              typeof primary(q.id) === 'string' ? (primary(q.id) as string) : ''
            "
            rows="2"
            @update:model-value="setPrimary(q.id, $event)"
          />

          <v-textarea
            :model-value="noteFor(q.id)"
            rows="2"
            class="mt-2"
            placeholder="Additional information (optional)…"
            @update:model-value="setNote(q.id, $event)"
          />
        </template>

        <v-textarea
          v-else-if="custom(q.id)"
          data-testid="custom-text"
          :model-value="customTextOf(q.id)"
          rows="2"
          placeholder="Explain what the agent got wrong (required)…"
          @update:model-value="setCustom(q.id, $event)"
        />

        <v-textarea
          v-else
          data-testid="waiver-text"
          :model-value="reasonOf(q.id)"
          rows="2"
          placeholder="Reason (required) — recorded in the refined issue…"
          @update:model-value="setReason(q.id, $event)"
        />

        <div class="d-flex flex-wrap ga-4 mt-1">
          <v-checkbox
            data-testid="toggle-custom"
            label="None of these fit — tell the agent"
            :model-value="custom(q.id)"
            density="compact"
            hide-details
            @update:model-value="toggleCustom(q.id, $event === true)"
          />
          <v-checkbox
            data-testid="toggle-waiver"
            :label="`${q.waiver_label || 'Unknown / N/A'} — give a reason`"
            :model-value="waived(q.id)"
            density="compact"
            hide-details
            @update:model-value="toggleWaiver(q.id, $event === true)"
          />
        </div>
      </div>
    </section>

    <div class="d-flex align-center ga-3 flex-wrap">
      <v-btn type="submit" color="primary" :disabled="!canSubmit">
        {{ submittingIncomplete ? 'Submit incomplete' : 'Submit answers' }}
      </v-btn>
      <v-btn type="button" variant="text" @click="onSaveDraft">
        Save progress
      </v-btn>
      <span v-if="submittingIncomplete" class="text-caption text-warning">
        Unanswered questions will be sent blank.
      </span>
      <span
        v-else-if="saveStatusLabel"
        class="text-caption text-medium-emphasis"
      >
        {{ saveStatusLabel }}
      </span>
    </div>
  </v-form>
</template>

<style scoped>
/* Cap the form to a comfortable reading measure so question text stays
   legible instead of stretching the full stage width. */
.qform {
  max-width: 44rem;
}
</style>

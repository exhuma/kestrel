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

const BADGE: Record<string, string> = {
  user: 'var(--user)',
  agent: 'var(--signal)',
  warn: 'var(--warn)',
  ok: 'var(--ok)',
  err: 'var(--err)',
  sys: 'var(--idle)',
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
  <form class="qform" @submit.prevent="onSubmit">
    <div class="qform__notice" role="status" v-if="justAdvanced">
      <span class="qform__notice-pulse" aria-hidden="true" />
      New questions arrived — your answers were kept.
    </div>

    <div
      v-if="softIssues.length"
      class="qform__issues qform__issues--soft"
      role="status"
    >
      <span class="qform__issues-glyph" aria-hidden="true">↻</span>
      <div>
        <p class="qform__issues-head">
          {{ softIssues.length }}
          specialist{{ softIssues.length > 1 ? 's' : '' }} didn't respond and
          will be retried when you submit your answers:
        </p>
        <ul class="qform__issues-list">
          <li v-for="i in softIssues" :key="i.profile">
            <span class="qform__issues-label">{{ i.label }}</span> —
            {{ i.reason }}
          </li>
        </ul>
      </div>
    </div>

    <div
      v-if="hardIssues.length"
      class="qform__issues qform__issues--hard"
      role="alert"
    >
      <span class="qform__issues-glyph" aria-hidden="true">!</span>
      <div>
        <p class="qform__issues-head">
          {{ hardIssues.length }}
          specialist{{ hardIssues.length > 1 ? 's' : '' }} failed after 3
          retries and {{ hardIssues.length > 1 ? 'were' : 'was' }} skipped:
        </p>
        <ul class="qform__issues-list">
          <li v-for="i in hardIssues" :key="i.profile">
            <span class="qform__issues-label">{{ i.label }}</span> —
            {{ i.reason }}
          </li>
        </ul>
      </div>
    </div>

    <div class="qtabs" role="tablist" v-if="groups.length > 1">
      <button
        v-for="g in groups"
        :key="g.profile.id"
        type="button"
        role="tab"
        class="qtab"
        :class="{
          'qtab--on': activeTab === g.profile.id,
          'qtab--done': groupComplete(g),
        }"
        :style="{ '--c': badgeColor(g.profile.badge) }"
        :aria-selected="activeTab === g.profile.id"
        @click="activeTab = g.profile.id"
      >
        <span class="qtab__dot" aria-hidden="true" />
        <span class="qtab__label">{{ g.profile.label }}</span>
        <span class="qtab__count mono">
          {{ g.answered }}/{{ g.questions.length }}
        </span>
      </button>
    </div>

    <section
      v-for="g in groups"
      v-show="activeTab === g.profile.id"
      :key="g.profile.id"
      class="qgroup"
      role="tabpanel"
    >
      <header class="qgroup__head" v-if="groups.length === 1">
        <span class="qbadge" :style="{ '--c': badgeColor(g.profile.badge) }">
          {{ g.profile.label }}
        </span>
        <span class="qgroup__progress mono">
          {{ g.answered }}/{{ g.questions.length }} answered
        </span>
      </header>

      <div
        v-for="q in g.questions"
        :key="q.id"
        class="qform__q"
        :class="{
          'qform__q--waived': waived(q.id),
          'qform__q--custom': custom(q.id),
        }"
        role="group"
        :aria-labelledby="`qp-${q.id}`"
      >
        <p :id="`qp-${q.id}`" class="qform__prompt">
          {{ q.prompt }}<span v-if="q.required" aria-hidden="true"> *</span>
        </p>
        <p v-if="q.why" class="qform__why mono">{{ q.why }}</p>

        <template v-if="!waived(q.id) && !custom(q.id)">
          <div v-if="q.type === 'single_select'" class="qform__options">
            <label v-for="o in q.options" :key="o.value" class="qform__option">
              <input
                type="radio"
                :name="q.id"
                :value="o.value"
                :checked="primary(q.id) === o.value"
                @change="setPrimary(q.id, o.value)"
              />
              {{ o.label }}
            </label>
          </div>

          <div v-else-if="q.type === 'multi_select'" class="qform__options">
            <label v-for="o in q.options" :key="o.value" class="qform__option">
              <input
                type="checkbox"
                :value="o.value"
                :checked="isChecked(q.id, o.value)"
                @change="
                  toggleMulti(
                    q.id,
                    o.value,
                    ($event.target as HTMLInputElement).checked,
                  )
                "
              />
              {{ o.label }}
            </label>
          </div>

          <div v-else-if="q.type === 'boolean'" class="qform__options">
            <label class="qform__option">
              <input
                type="radio"
                :name="q.id"
                :checked="primary(q.id) === true"
                @change="setPrimary(q.id, true)"
              />
              Yes
            </label>
            <label class="qform__option">
              <input
                type="radio"
                :name="q.id"
                :checked="primary(q.id) === false"
                @change="setPrimary(q.id, false)"
              />
              No
            </label>
          </div>

          <textarea
            v-else
            class="field"
            rows="2"
            :value="
              typeof primary(q.id) === 'string' ? (primary(q.id) as string) : ''
            "
            @input="
              setPrimary(q.id, ($event.target as HTMLTextAreaElement).value)
            "
          />

          <textarea
            class="field qform__note"
            rows="2"
            :value="noteFor(q.id)"
            placeholder="Additional information (optional)…"
            @input="setNote(q.id, ($event.target as HTMLTextAreaElement).value)"
          />
        </template>

        <div v-else-if="custom(q.id)" class="qform__custom">
          <textarea
            class="field"
            rows="2"
            :value="customTextOf(q.id)"
            placeholder="Explain what the agent got wrong (required)…"
            @input="
              setCustom(q.id, ($event.target as HTMLTextAreaElement).value)
            "
          />
        </div>

        <div v-else class="qform__waiver">
          <textarea
            class="field"
            rows="2"
            :value="reasonOf(q.id)"
            :placeholder="`Reason (required) — recorded in the refined issue…`"
            @input="
              setReason(q.id, ($event.target as HTMLTextAreaElement).value)
            "
          />
        </div>

        <div class="qform__toggles">
          <label class="qform__toggle qform__toggle--custom">
            <input
              type="checkbox"
              :checked="custom(q.id)"
              @change="
                toggleCustom(q.id, ($event.target as HTMLInputElement).checked)
              "
            />
            None of these fit — tell the agent
          </label>
          <label class="qform__toggle qform__toggle--waive">
            <input
              type="checkbox"
              :checked="waived(q.id)"
              @change="
                toggleWaiver(q.id, ($event.target as HTMLInputElement).checked)
              "
            />
            {{ q.waiver_label || 'Unknown / N/A' }} — give a reason
          </label>
        </div>
      </div>
    </section>

    <div class="qform__actions">
      <button type="submit" class="btn btn--primary" :disabled="!canSubmit">
        {{ submittingIncomplete ? 'Submit incomplete' : 'Submit answers' }}
      </button>
      <button type="button" class="btn btn--ghost" @click="onSaveDraft">
        Save progress
      </button>
      <span v-if="submittingIncomplete" class="qform__incomplete mono">
        Unanswered questions will be sent blank.
      </span>
      <span class="qform__savestatus mono" v-else-if="saveStatusLabel">
        {{ saveStatusLabel }}
      </span>
    </div>
  </form>
</template>

<style scoped>
/* Cap the form to a comfortable reading measure (~66ch) so question
   text stays legible instead of stretching the full stage width. */
.qform {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 44rem;
}

/* One tab per specialist — same mnemonic + badge tone as the session
   chips, so a profile reads as one identity across the whole view. */
.qtabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  border-bottom: 1px solid var(--line);
  padding-bottom: 10px;
}
.qtab {
  --c: var(--idle);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-radius: var(--r-md);
  background: var(--ink-700);
  border: 1px solid var(--line);
  color: var(--text-mid);
  cursor: pointer;
  font-family: var(--font-sans);
  transition:
    border-color 0.15s ease,
    color 0.15s ease,
    background 0.15s ease;
}
.qtab:hover {
  color: var(--text-hi);
  border-color: var(--c);
}
.qtab:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--signal-glow);
}
.qtab--on {
  color: var(--text-hi);
  border-color: var(--c);
  background: var(--ink-650);
}
.qtab__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
  background: var(--c);
  opacity: 0.5;
}
.qtab--on .qtab__dot,
.qtab--done .qtab__dot {
  opacity: 1;
}
.qtab--done .qtab__dot {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--c) 22%, transparent);
}
.qtab__label {
  font-size: 12.5px;
  font-weight: 600;
}
.qtab__count {
  font-size: 11px;
  color: var(--text-dim);
}
.qtab--on .qtab__count {
  color: var(--text-mid);
}

.qgroup {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.qgroup__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.qbadge {
  --c: var(--idle);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 999px;
  color: var(--ink-900);
  background: var(--c);
}
.qgroup__progress {
  font-size: 11px;
  color: var(--text-dim);
}
.qform__q {
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.qform__q--waived {
  border-style: dashed;
  border-color: var(--warn);
}
.qform__q--custom {
  border-style: dashed;
  border-color: var(--signal);
}
.qform__prompt {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.45;
  color: var(--text-hi);
}
.qform__why {
  font-size: 11.5px;
  color: var(--text-dim);
  margin: 4px 0 0;
  line-height: 1.5;
}
.qform__options {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.qform__option {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-mid);
}
/* Optional "additional information" note, visually secondary to the
   primary answer it annotates. */
.qform__note {
  margin-top: 2px;
  opacity: 0.9;
}
.qform__toggles {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin-top: 2px;
}
.qform__toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.qform__toggle--waive {
  color: var(--warn);
}
.qform__toggle--custom {
  color: var(--signal);
}
.qform__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.qform__actions .btn {
  width: auto;
  padding-left: 22px;
  padding-right: 22px;
}
.qform__savestatus {
  font-size: 11px;
  color: var(--text-dim);
}
.qform__incomplete {
  font-size: 11px;
  color: var(--warn);
}

/* Transient banner shown when the round genuinely advances, matching
   the working--attention pulse used elsewhere for "needs your eyes". */
.qform__notice {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid var(--warn);
  border-radius: var(--r-md);
  background: var(--ink-700);
  color: var(--text-hi);
  font-size: 12.5px;
}
.qform__notice-pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--warn);
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--warn) 45%, transparent);
  animation: qform-notice-pulse 1.4s ease-out infinite;
}
@keyframes qform-notice-pulse {
  0% {
    box-shadow: 0 0 0 0 color-mix(in srgb, var(--warn) 45%, transparent);
  }
  70% {
    box-shadow: 0 0 0 7px transparent;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}

/* Persistent record of specialists that failed to respond this round,
   shown with the questionnaire after the live chips have cleared. Soft
   (retrying) uses the warn tone; hard (given up) uses the error tone. */
.qform__issues {
  --tone: var(--err);
  display: flex;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid var(--tone);
  border-left: 3px solid var(--tone);
  border-radius: var(--r-md);
  background: color-mix(in srgb, var(--tone) 12%, var(--ink-800));
  color: var(--text-hi);
  font-size: 12.5px;
}
.qform__issues--soft {
  --tone: var(--warn);
}
.qform__issues--hard {
  --tone: var(--err);
}
.qform__issues-glyph {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  flex: none;
  font-size: 11px;
  font-weight: 700;
  color: var(--ink-900);
  background: var(--tone);
}
.qform__issues-head {
  margin: 0 0 4px;
  font-weight: 600;
}
.qform__issues-list {
  margin: 0;
  padding-left: 16px;
  color: var(--text-mid);
}
.qform__issues-label {
  color: var(--text-hi);
  font-weight: 600;
}
</style>

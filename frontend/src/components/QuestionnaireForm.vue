<script setup lang="ts">
import { reactive, computed, ref, watch } from 'vue'
import type { Questionnaire, WaiverAnswer } from '../types/questionnaire'
import type { ProfileGroup } from '../lib/questionnaire'
import {
  allRequiredAnswered, groupByProfile, isAnswered, isWaiver,
} from '../lib/questionnaire'
import { debounce } from '../lib/debounce'

const props = defineProps<{
  questionnaire: Questionnaire
  draftAnswers?: Record<string, unknown>
  round: number
}>()
const emit = defineEmits<{
  submit: [answers: Record<string, unknown>]
  saveDraft: [answers: Record<string, unknown>]
}>()

const answers = reactive<Record<string, unknown>>({ ...(props.draftAnswers ?? {}) })
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
    setTimeout(() => { justAdvanced.value = false }, 4000)
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
  idle: '', dirty: 'Unsaved changes…', saving: 'Saving…',
  saved: 'Answers saved',
}
const saveStatusLabel = computed(() => SAVE_STATUS_LABEL[saveStatus.value])

const groups = computed(() => groupByProfile(props.questionnaire, answers))
const canSubmit = computed(() =>
  allRequiredAnswered(props.questionnaire, answers),
)

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
  void flushSave()
}
</script>

<template>
  <form class="qform" @submit.prevent="onSubmit">
    <div class="qform__notice" role="status" v-if="justAdvanced">
      <span class="qform__notice-pulse" aria-hidden="true" />
      New questions arrived — your answers were kept.
    </div>

    <div class="qtabs" role="tablist" v-if="groups.length > 1">
      <button
        v-for="g in groups"
        :key="g.profile.id"
        type="button"
        role="tab"
        class="qtab"
        :class="{ 'qtab--on': activeTab === g.profile.id,
          'qtab--done': groupComplete(g) }"
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
        :class="{ 'qform__q--waived': waived(q.id) }"
        role="group"
        :aria-labelledby="`qp-${q.id}`"
      >
        <p :id="`qp-${q.id}`" class="qform__prompt">
          {{ q.prompt }}<span v-if="q.required" aria-hidden="true"> *</span>
        </p>
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
      </div>
    </section>

    <div class="qform__actions">
      <button type="submit" class="btn btn--primary" :disabled="!canSubmit">
        Submit answers
      </button>
      <button type="button" class="btn btn--ghost" @click="onSaveDraft">
        Save progress
      </button>
      <span class="qform__savestatus mono" v-if="saveStatusLabel">
        {{ saveStatusLabel }}
      </span>
    </div>
  </form>
</template>

<style scoped>
/* Cap the form to a comfortable reading measure (~66ch) so question
   text stays legible instead of stretching the full stage width. */
.qform { display: flex; flex-direction: column; gap: 18px; max-width: 44rem; }

/* One tab per specialist — same mnemonic + badge tone as the session
   chips, so a profile reads as one identity across the whole view. */
.qtabs {
  display: flex; flex-wrap: wrap; gap: 6px;
  border-bottom: 1px solid var(--line); padding-bottom: 10px;
}
.qtab {
  --c: var(--idle);
  display: inline-flex; align-items: center; gap: 8px;
  padding: 7px 12px; border-radius: var(--r-md);
  background: var(--ink-700); border: 1px solid var(--line);
  color: var(--text-mid); cursor: pointer; font-family: var(--font-sans);
  transition: border-color 0.15s ease, color 0.15s ease,
    background 0.15s ease;
}
.qtab:hover { color: var(--text-hi); border-color: var(--c); }
.qtab:focus-visible {
  outline: none; box-shadow: 0 0 0 3px var(--signal-glow);
}
.qtab--on {
  color: var(--text-hi); border-color: var(--c);
  background: var(--ink-650);
}
.qtab__dot {
  width: 8px; height: 8px; border-radius: 50%; flex: none;
  background: var(--c); opacity: 0.5;
}
.qtab--on .qtab__dot, .qtab--done .qtab__dot { opacity: 1; }
.qtab--done .qtab__dot {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--c) 22%, transparent);
}
.qtab__label { font-size: 12.5px; font-weight: 600; }
.qtab__count { font-size: 11px; color: var(--text-dim); }
.qtab--on .qtab__count { color: var(--text-mid); }

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
.qform__prompt {
  margin: 0; font-size: 13.5px; font-weight: 600; line-height: 1.45;
  color: var(--text-hi);
}
.qform__why { font-size: 11.5px; color: var(--text-dim); margin: 4px 0 0;
  line-height: 1.5; }
.qform__options { display: flex; flex-direction: column; gap: 6px; }
.qform__option { display: flex; align-items: center; gap: 8px;
  font-size: 12.5px; color: var(--text-mid); }
.qform__waivetoggle { display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--warn); margin-top: 2px; }
.qform__actions { display: flex; align-items: center; gap: 10px; }
.qform__actions .btn { width: auto; padding-left: 22px; padding-right: 22px; }
.qform__savestatus { font-size: 11px; color: var(--text-dim); }

/* Transient banner shown when the round genuinely advances, matching
   the working--attention pulse used elsewhere for "needs your eyes". */
.qform__notice {
  display: flex; align-items: center; gap: 10px; padding: 10px 14px;
  border: 1px solid var(--warn); border-radius: var(--r-md);
  background: var(--ink-700); color: var(--text-hi); font-size: 12.5px;
}
.qform__notice-pulse {
  width: 8px; height: 8px; border-radius: 50%; background: var(--warn);
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--warn) 45%, transparent);
  animation: qform-notice-pulse 1.4s ease-out infinite;
}
@keyframes qform-notice-pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--warn) 45%, transparent); }
  70% { box-shadow: 0 0 0 7px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}
</style>

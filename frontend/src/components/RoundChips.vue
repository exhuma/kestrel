<script setup lang="ts">
import { computed } from 'vue'
import type { RoundChip, StepSession } from '../types/workflows'

const props = defineProps<{
  /** Frozen chips from every completed round of this step, oldest first. */
  roundHistory: RoundChip[]
  /** Chips still live right now (spinner, no separator around them). */
  activeSessions: StepSession[]
  /** The session id currently expanded in the telemetry drawer, if any. */
  expandedSessionId: string | null
}>()

const emit = defineEmits<{
  'toggle-session': [sessionId: string | null]
}>()

// Consecutive history chips sharing a round_index render as one group,
// with a separator before the next group — so each retire/replace of a
// step's live chips (coordinator, then specialists, then writer, …) reads
// as its own round instead of one long undifferentiated row.
const groups = computed(() => {
  const out: { key: string; chips: RoundChip[] }[] = []
  for (const chip of props.roundHistory) {
    const last = out.at(-1)
    if (last && last.chips[0].round_index === chip.round_index) {
      last.chips.push(chip)
    } else {
      out.push({ key: `${chip.step}-${chip.round_index}`, chips: [chip] })
    }
  }
  return out
})

// Crew-chip badge token → Vuetify colour (mirrors WorkflowPanel's map).
const BADGE_COLOR: Record<string, string | undefined> = {
  user: 'info',
  agent: 'primary',
  warn: 'warning',
  ok: 'success',
  err: 'error',
  sys: undefined,
}
function badgeColor(token: string): string | undefined {
  return BADGE_COLOR[token]
}
</script>

<template>
  <div class="d-flex flex-wrap align-center ga-2">
    <template v-for="(group, gi) in groups" :key="group.key">
      <v-divider v-if="gi > 0" vertical class="mx-1" />
      <v-chip
        v-for="chip in group.chips"
        :key="chip.session_id ?? `${chip.profile_id}-${chip.round_index}`"
        :color="chip.status === 'error' ? 'error' : badgeColor(chip.badge)"
        :variant="expandedSessionId === chip.session_id ? 'flat' : 'tonal'"
        :disabled="!chip.session_id"
        :title="chip.status === 'error' ? (chip.error ?? undefined) : undefined"
        @click="emit('toggle-session', chip.session_id)"
      >
        <template #prepend>
          <v-icon
            :icon="chip.status === 'error' ? '$alertCircle' : '$checkCircle'"
            size="small"
            class="me-1"
          />
        </template>
        {{ chip.label }}
        <span
          v-if="chip.status === 'error' && chip.error"
          class="ms-1 text-truncate chip__activity"
        >
          · {{ chip.error }}
        </span>
      </v-chip>
    </template>

    <v-divider
      v-if="groups.length && activeSessions.length"
      vertical
      class="mx-1"
    />
    <v-chip
      v-for="s in activeSessions"
      :key="s.session_id ?? s.profile_id"
      :color="s.status === 'error' ? 'error' : badgeColor(s.badge)"
      :variant="expandedSessionId === s.session_id ? 'flat' : 'tonal'"
      :disabled="!s.session_id"
      :title="s.status === 'error' ? (s.error ?? undefined) : undefined"
      @click="emit('toggle-session', s.session_id)"
    >
      <template #prepend>
        <v-progress-circular
          v-if="s.status === 'running'"
          indeterminate
          size="12"
          width="2"
          class="me-2"
        />
        <v-icon
          v-else-if="s.status === 'error'"
          icon="$alertCircle"
          size="small"
          class="me-1"
        />
      </template>
      {{ s.label }}
      <span
        v-if="s.status === 'error' && s.error"
        class="ms-1 text-truncate chip__activity"
      >
        · {{ s.error }}
      </span>
      <span
        v-else-if="s.activity"
        class="ms-1 text-truncate chip__activity text-medium-emphasis"
      >
        · {{ s.activity }}
      </span>
    </v-chip>
  </div>
</template>

<style scoped>
/* An error/activity hint on a crew chip can be long: keep the chip compact. */
.chip__activity {
  max-width: 22ch;
}
</style>

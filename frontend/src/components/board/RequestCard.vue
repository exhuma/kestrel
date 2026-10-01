<script setup lang="ts">
// One request's board card (FR-003/FR-004/FR-005): source ref + human
// title (never a bare workflow id), exact phase in words with its
// position in the ten-phase sequence, its cards by state as a colour bar,
// and the attention treatment.
// `v-card`'s own `to` prop makes the whole card a router link — keyboard
// reachable and openable via Enter for free (FR-007), no custom
// keydown handling needed.
import { computed } from 'vue'
import StateBar from './StateBar.vue'
import ActivityLine from '../common/ActivityLine.vue'
import type { AttentionState, BoardRequest } from '../../lib/stages'
import { describeMoves } from '../../lib/awaiting'

const props = defineProps<{ request: BoardRequest }>()

const PHASE_COUNT = 10

// Only a real problem, or a finished request, tints the whole card. A
// request waiting on its human is the normal flow, so only its chip is
// coloured.
const CARD_TINT: Record<AttentionState, string | undefined> = {
  none: undefined,
  'your-move': undefined,
  'cap-reached': undefined,
  quarantined: 'error',
  failed: 'error',
  done: 'success',
  cancelled: undefined,
}

const CHIP_COLOR: Record<AttentionState, string | undefined> = {
  none: undefined,
  'your-move': 'primary',
  'cap-reached': 'info',
  quarantined: 'error',
  failed: 'error',
  done: 'success',
  cancelled: undefined,
}

const ATTENTION_LABEL: Record<AttentionState, string> = {
  none: '',
  'your-move': 'Your move',
  'cap-reached': 'Round cap reached',
  quarantined: 'Quarantined',
  failed: 'Failed',
  done: 'Done',
  cancelled: 'Cancelled',
}

const ATTENTION_ICON: Partial<Record<AttentionState, string>> = {
  'your-move': '$alertCircle',
  'cap-reached': '$alertCircle',
  quarantined: '$shieldAlert',
  failed: '$alertCircle',
  done: '$checkCircle',
  cancelled: '$close',
}

const manualTasks = computed(() => {
  const count = props.request.summary.open_manual_task_count
  const noun = count === 1 ? 'task' : 'tasks'
  return count > 0 ? `${count} manual ${noun} assigned to you` : ''
})

/** Whose move it is, and what: "CAB: decide strategic fit" (feature 035). */
const moves = computed(() => describeMoves(props.request.summary.awaiting))

const tint = computed(() => CARD_TINT[props.request.attention])
const chipColor = computed(() => CHIP_COLOR[props.request.attention])
const label = computed(() => ATTENTION_LABEL[props.request.attention])
const icon = computed(() => ATTENTION_ICON[props.request.attention])
</script>

<template>
  <v-card
    :to="{ name: 'cockpit', params: { id: request.summary.id } }"
    :color="tint"
    variant="tonal"
    class="mb-2"
  >
    <v-card-item>
      <template v-if="icon" #prepend>
        <v-icon :icon="icon" />
      </template>
      <v-card-title>{{ request.summary.title }}</v-card-title>
      <v-card-subtitle>{{ request.summary.task_label }}</v-card-subtitle>
    </v-card-item>

    <v-card-text>
      <ActivityLine :activity="request.summary.activity" class="mb-2" />
      <div class="text-body-2 mb-1">
        {{ request.summary.phase }}
        <span v-if="request.position.ordinal !== null">
          ({{ request.position.ordinal }} of {{ PHASE_COUNT }})
        </span>
      </div>
      <StateBar :state-counts="request.summary.state_counts" />

      <v-chip
        v-if="request.attention !== 'none'"
        :color="chipColor"
        size="small"
        class="mt-2"
      >
        {{ label }}
      </v-chip>
      <v-chip
        v-if="manualTasks"
        color="info"
        size="small"
        prepend-icon="$account"
        class="mt-2 ml-1"
      >
        {{ manualTasks }}
      </v-chip>
      <div
        v-if="request.attention !== 'none' && moves"
        class="text-body-2 mt-1"
        data-testid="moves"
      >
        {{ moves }}
      </div>
    </v-card-text>
  </v-card>
</template>

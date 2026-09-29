<script setup lang="ts">
// The structural view of a request (FR-019), replacing the dependency
// graph: the ten phases in order, where this request has got to, and
// which of them are gates. Each step carries its status (feature 034):
// a finished request reads as a row of outcomes, not a blank line.
//
// `density="compact"` + `align="start"` are not cosmetic — research R3's
// T037 addendum records the measurement. They put every label on one
// baseline under its dot, so ten of them fit on a single line at the
// 1280 px target and the sequence reads left-to-right. The default
// alternating layout wraps the long gate labels and makes the eye
// zig-zag. Below ~1100 px labels wrap rather than truncate, so nothing
// is ever hidden.
import { computed } from 'vue'
import { PHASE_ORDER, phasePosition } from '../../lib/stages'
import type { PhaseStatus, PhaseStatusValue } from '../../types/workflows'

const props = defineProps<{
  /** The phase the request is in, as the server reports it. */
  phase: string
  /** Every step's status, as the server decides it (feature 034). A
   *  step the server did not report reads as not reached. */
  phases: PhaseStatus[]
}>()

/** The gate phases — the points where the pipeline waits on a decision
 *  rather than doing work. Marked beside the label (FR-011), since the
 *  dot carries the step's status. */
const GATE_PHASES: readonly string[] = [
  'CAB-1 - strategic fit',
  'PRD sign-off',
  'CAB-2 - go/no-go',
]

/** Icon, colour and word per status: each is told apart by its icon and
 *  its word, never by colour alone. */
const LOOK: Record<
  PhaseStatusValue,
  { icon: string; color: string | undefined; label: string }
> = {
  done: { icon: '$checkCircle', color: 'success', label: 'Done' },
  active: { icon: '$progressClock', color: 'primary', label: 'In progress' },
  waiting: {
    icon: '$accountClock',
    color: 'warning',
    label: 'Waiting for you',
  },
  problem: { icon: '$alertCircle', color: 'error', label: 'Problem' },
  skipped: { icon: '$minusCircleOutline', color: 'grey', label: 'Skipped' },
  upcoming: { icon: '$circleOutline', color: undefined, label: 'Not reached' },
}

const position = computed(() => phasePosition(props.phase))
const statusOf = computed(
  () => new Map(props.phases.map((p) => [p.name, p.status])),
)

function look(phase: string) {
  return LOOK[statusOf.value.get(phase) ?? 'upcoming']
}

function isCurrent(phase: string): boolean {
  return phase === props.phase
}
</script>

<template>
  <div>
    <v-timeline
      direction="horizontal"
      density="compact"
      align="start"
      truncate-line="both"
      line-thickness="2"
    >
      <v-timeline-item
        v-for="p in PHASE_ORDER"
        :key="p"
        size="small"
        :dot-color="look(p).color"
        :icon="look(p).icon"
        :data-status="statusOf.get(p) ?? 'upcoming'"
      >
        <div
          class="text-caption"
          :class="isCurrent(p) ? 'font-weight-bold' : 'text-medium-emphasis'"
        >
          <v-icon
            v-if="GATE_PHASES.includes(p)"
            icon="$shieldAlert"
            size="x-small"
            aria-label="Gate"
            data-testid="gate-mark"
          />
          {{ p }}
        </div>
        <div
          class="text-caption"
          :class="look(p).color ? `text-${look(p).color}` : 'text-disabled'"
        >
          {{ look(p).label }}
        </div>
      </v-timeline-item>
    </v-timeline>

    <!-- An unrecognised phase still names itself, with no position claimed
         (data-model.md §2 "PhasePosition"). -->
    <v-alert
      v-if="position.ordinal === null && !position.isTerminal"
      type="info"
      density="compact"
      class="mt-2"
    >
      Current phase: {{ phase }} — not part of the standard sequence.
    </v-alert>
  </div>
</template>

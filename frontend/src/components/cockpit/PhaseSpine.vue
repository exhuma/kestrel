<script setup lang="ts">
// The structural view of a request (FR-019), replacing the dependency
// graph: the ten phases in order, where this request has got to, and
// which of them are gates.
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

const props = defineProps<{
  /** The phase the request is in, as the server reports it. */
  phase: string
}>()

/** The gate phases — the points where the pipeline waits on a decision
 *  rather than doing work. Distinguished by icon (FR-011). */
const GATE_PHASES: readonly string[] = [
  'CAB-1 - strategic fit',
  'PRD sign-off',
  'CAB-2 - go/no-go',
]

const position = computed(() => phasePosition(props.phase))

/** True once the request is past *phase*. An unrecognised current phase
 *  has no position, so nothing is claimed to be passed — the spine shows
 *  the sequence without asserting progress it cannot know. */
function isPassed(index: number): boolean {
  const ordinal = position.value.ordinal
  return ordinal !== null && index + 1 < ordinal
}

function isCurrent(phase: string): boolean {
  return phase === props.phase
}

function dotColor(phase: string, index: number): string | undefined {
  if (isCurrent(phase)) return 'primary'
  if (isPassed(index)) return 'success'
  return undefined
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
        v-for="(p, i) in PHASE_ORDER"
        :key="p"
        size="x-small"
        :dot-color="dotColor(p, i)"
        :icon="GATE_PHASES.includes(p) ? '$shieldAlert' : undefined"
      >
        <div
          class="text-caption"
          :class="isCurrent(p) ? 'font-weight-bold' : 'text-medium-emphasis'"
        >
          {{ p }}
        </div>
        <div v-if="isCurrent(p)" class="text-caption text-primary">
          Current phase
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

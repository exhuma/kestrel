<script setup lang="ts">
// The round cap indicator (FR-024, FR-027): reuses `PhaseProgress` with
// the round cap in place of the ten-phase count — its own doc comment
// names this as the intended second use. `RoundChips.vue` is deliberately
// not recovered here; research R5 explains why a cap indicator is a
// smaller, fresher build than adapting a per-round chip list.
import { computed } from 'vue'
import PhaseProgress from '../common/PhaseProgress.vue'

const props = defineProps<{
  current: number | null
  cap: number | null
}>()

const isRoundCapped = computed(
  () => props.current !== null && props.cap !== null,
)

// The wording is a function of the state, not a separate flag, so the
// two cannot disagree (data-model.md's `RoundState`).
const isFinalRound = computed(
  () => isRoundCapped.value && props.current === props.cap,
)

const label = computed(() =>
  isRoundCapped.value
    ? `Round ${props.current} of ${props.cap}`
    : 'Single round',
)
</script>

<template>
  <div class="d-flex align-center ga-3 flex-wrap">
    <v-chip
      :color="isFinalRound ? 'warning' : undefined"
      data-testid="round-chip"
    >
      {{ label }}
    </v-chip>
    <PhaseProgress
      v-if="isRoundCapped"
      :count="cap as number"
      :ordinal="current"
      class="flex-1-1"
    />
    <span
      v-if="isFinalRound"
      class="text-caption text-warning"
      data-testid="final-round-notice"
    >
      Last chance to answer before assumptions are recorded in the PRD.
    </span>
  </div>
</template>

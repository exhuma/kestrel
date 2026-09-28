<script setup lang="ts">
// A request's position within the ten-phase sequence (FR-004), shared
// between the stage board's cards and the cockpit's spine. A `null`
// ordinal (an unrecognised phase, or the synthetic `done` phase) renders
// no position bar — there is nothing meaningful to mark.
defineProps<{
  /** Total segments in the sequence (10 phases; the interview round
   *  indicator reuses this component with the round cap instead). */
  count: number
  /** 1-based position within the sequence, or `null` to render nothing. */
  ordinal: number | null
}>()
</script>

<template>
  <v-progress-linear
    v-if="ordinal !== null"
    :model-value="(ordinal / count) * 100"
    :chunk-count="count"
    variant="split"
    color="primary"
    height="8"
  />
</template>

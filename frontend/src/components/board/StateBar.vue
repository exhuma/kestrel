<script setup lang="ts">
// A request's cards by state, as one colour-coded row that fills the
// card's width, with a legend below so the colours are never the only
// thing that carries the meaning. Each segment's width is proportional
// to its count; a lone card still gets a visible sliver.
import { computed } from 'vue'
import type { CardState } from '../../types/workflows'
import { stateSegments } from '../../lib/stateBar'

const props = defineProps<{
  stateCounts: Partial<Record<CardState, number>>
}>()

const segments = computed(() => stateSegments(props.stateCounts))
const summary = computed(() => segments.value.map((s) => s.label).join(', '))
</script>

<template>
  <div v-if="segments.length" class="state-bar mt-2">
    <div
      class="d-flex flex-nowrap ga-1"
      role="img"
      :aria-label="`Cards: ${summary}`"
      data-testid="state-bar"
    >
      <div
        v-for="segment in segments"
        :key="segment.state"
        class="state-bar__segment"
        :style="{ flex: `${segment.count} 1 0` }"
        :title="segment.label"
        :aria-label="segment.label"
        :data-state="segment.state"
      >
        <v-progress-linear
          :model-value="100"
          :color="segment.color"
          height="8"
          rounded
        />
      </div>
    </div>
    <div class="d-flex flex-wrap mt-1" data-testid="state-legend">
      <v-chip
        v-for="segment in segments"
        :key="segment.state"
        size="x-small"
        variant="text"
        class="px-1"
      >
        <v-icon icon="$circle" :color="segment.color" size="x-small" start />
        {{ segment.label }}
      </v-chip>
    </div>
  </div>
</template>

<style scoped>
.state-bar__segment {
  min-width: 4px;
}
</style>

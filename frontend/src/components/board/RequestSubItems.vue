<script setup lang="ts">
// A request's own sub-work, nested inside its board card rather than
// appearing as separate top-level cards (FR-002). Two distinct sources,
// both already on the listing row — no per-workflow fetch:
//
// 1. The request's own cards, as a compact per-state count (the listing
//    carries aggregate `state_counts`, not individually named cards —
//    those are the cockpit's job, backed by the full snapshot).
// 2. Its decomposition children — separate workflows, matched via the
//    FR-040 parent link (`lib/stages.ts`'s `groupByStage`).
import { computed } from 'vue'
import type { BoardWorkflowSummary, CardState } from '../../types/workflows'

const props = defineProps<{
  stateCounts: Partial<Record<CardState, number>>
  children: BoardWorkflowSummary[]
}>()

const ownCardCounts = computed(() =>
  Object.entries(props.stateCounts).filter(([, count]) => (count ?? 0) > 0),
)

function stateLabel(state: string): string {
  return state.replace(/_/g, ' ')
}
</script>

<template>
  <v-list
    v-if="ownCardCounts.length > 0 || children.length > 0"
    density="compact"
    class="request-sub-items"
  >
    <v-list-item
      v-for="[state, count] in ownCardCounts"
      :key="state"
      :title="`${count} ${stateLabel(state)}`"
      prepend-icon="$subdirectoryArrowRight"
    />
    <v-list-item
      v-for="child in children"
      :key="child.id"
      :title="child.title"
      :subtitle="child.task_label"
      prepend-icon="$subdirectoryArrowRight"
    />
  </v-list>
</template>

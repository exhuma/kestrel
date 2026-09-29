<script setup lang="ts">
// A request's own sub-work, nested inside its board card rather than
// appearing as separate top-level cards (FR-002): its cards, as a compact
// per-state count. The listing carries aggregate `state_counts`, not
// individually named cards — those are the cockpit's job, backed by the
// full snapshot, where the cockpit's work list names each card and why a
// cancelled or failed one ended (feature 034). A request's approved tasks are among these cards
// (feature 031); decomposition no longer creates separate workflows.
import { computed } from 'vue'
import type { CardState } from '../../types/workflows'

const props = defineProps<{
  stateCounts: Partial<Record<CardState, number>>
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
    v-if="ownCardCounts.length > 0"
    density="compact"
    class="request-sub-items"
  >
    <v-list-item
      v-for="[state, count] in ownCardCounts"
      :key="state"
      :title="`${count} ${stateLabel(state)}`"
      prepend-icon="$subdirectoryArrowRight"
    />
  </v-list>
</template>

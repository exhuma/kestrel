<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import { projectBoardGraph } from '../lib/boardGraph'
import type { WorkCardRelation, WorkCardSummary } from '../types/workflows'

// Read-only: no drag-to-reposition, no drag-to-connect. This view only
// explains and navigates the same board data List already fully
// controls (spec.md US6 Scenario 5) — it never itself mutates state.

const props = defineProps<{
  cards: WorkCardSummary[]
  relationships: WorkCardRelation[]
}>()

const emit = defineEmits<{ select: [cardId: string] }>()

const graph = computed(() => projectBoardGraph(props.cards, props.relationships))

// fit-view-on-init only fires once, on mount — it does not refit when the
// canvas itself is resized afterward (e.g. the card-detail pane opening
// narrows it), which otherwise leaves nodes rendered behind that pane.
// A ResizeObserver on the canvas element keeps the view in sync with
// whatever width it actually has right now.
const { fitView } = useVueFlow()
const graphRoot = ref<HTMLElement | null>(null)
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  if (!graphRoot.value) return
  resizeObserver = new ResizeObserver(() => {
    void fitView({ padding: 0.2 })
  })
  resizeObserver.observe(graphRoot.value)
})
onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})

const STATE_COLORS: Record<string, string | undefined> = {
  ready: 'info',
  claimed: 'primary',
  awaiting_human: 'warning',
  review: 'secondary',
  quarantined: 'error',
  done: 'success',
  failed: 'error',
}

function colorFor(state: string): string | undefined {
  return STATE_COLORS[state]
}
</script>

<template>
  <div
    ref="graphRoot"
    class="graph-root"
    role="application"
    aria-label="Workflow dependency graph"
  >
    <VueFlow
      :nodes="graph.nodes"
      :edges="graph.edges"
      :nodes-draggable="false"
      :nodes-connectable="false"
      :edges-updatable="false"
      fit-view-on-init
      @node-click="(e) => emit('select', e.node.id)"
    >
      <template #node-default="{ data }">
        <v-card
          density="compact"
          variant="tonal"
          :color="colorFor(data.card.state)"
          class="pa-2 graph-node"
          role="button"
          tabindex="0"
          @keyup.enter="emit('select', data.card.id)"
        >
          <div class="text-caption font-weight-bold text-truncate">
            {{ data.card.title }}
          </div>
          <div class="text-caption">{{ data.card.state }}</div>
        </v-card>
      </template>
    </VueFlow>
  </div>
</template>

<style scoped>
.graph-root {
  height: 70vh;
  width: 100%;
}
.graph-node {
  min-width: 160px;
}
</style>

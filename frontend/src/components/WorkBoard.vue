<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  onMounted,
  onUnmounted,
  ref,
} from 'vue'
import { useBoard } from '../composables/useBoard'
import WorkCardDetail from './WorkCardDetail.vue'
import PanelLoading from './PanelLoading.vue'
import PanelError from './PanelError.vue'
import { CARD_STATES } from '../types/workflows'
import type { WorkCardSummary } from '../types/workflows'

// The graph view is a read-only navigation enhancement over the same
// data (spec.md US6) — lazy-loaded so its cost (Vue Flow) is never paid
// by an operator who only ever uses the accessible List view.
const WorkflowGraph = defineAsyncComponent({
  loader: () => import('./WorkflowGraph.vue'),
  loadingComponent: PanelLoading,
  errorComponent: PanelError,
  delay: 200,
})

const {
  workflows,
  current,
  error,
  refresh,
  startList,
  stopList,
  select,
  stop,
} = useBoard()

const layout = ref<'list' | 'graph'>('list')
const selectedCardId = ref<string | null>(null)

onMounted(() => {
  void refresh()
  startList()
})
onUnmounted(() => {
  stop()
  stopList()
})

const STATE_LABELS: Record<string, string> = {
  ready: 'Ready',
  claimed: 'Claimed',
  waiting_dependency: 'Waiting on dependency',
  awaiting_human: 'Awaiting a decision',
  review: 'In review',
  quarantined: 'Quarantined',
  done: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

const groups = computed(() => {
  const cards = current.value?.cards ?? []
  return CARD_STATES.map((state) => ({
    state,
    label: STATE_LABELS[state],
    cards: cards.filter((c) => c.state === state),
  })).filter((g) => g.cards.length > 0)
})

const selectedCard = computed<WorkCardSummary | null>(() => {
  const cards = current.value?.cards ?? []
  return cards.find((c) => c.id === selectedCardId.value) ?? null
})

function selectWorkflow(id: string): void {
  selectedCardId.value = null
  void select(id)
}
</script>

<template>
  <div class="board-root d-flex">
    <!-- Plain flex panes, not v-navigation-drawer/v-main: this component
         is mounted *inside* App.vue's own v-main, so it must not nest
         another app-shell layout (those require a direct v-app ancestor
         to inject into, see Vuetify's `useLayoutItem`). -->
    <nav class="board-sidebar" aria-label="Workflows">
      <v-list nav density="compact">
        <v-list-item
          v-for="w in workflows"
          :key="w.id"
          :active="w.id === current?.id"
          :title="w.task_label"
          :subtitle="w.status"
          @click="selectWorkflow(w.id)"
        >
          <template v-if="w.action_required_count > 0" #append>
            <v-chip size="x-small" color="warning">{{
              w.action_required_count
            }}</v-chip>
          </template>
        </v-list-item>
      </v-list>
    </nav>

    <div class="board-main">
      <v-alert v-if="error" type="error" density="compact">{{ error }}</v-alert>

      <template v-if="current">
        <v-toolbar density="compact" flat>
          <v-toolbar-title>{{ current.task_label }}</v-toolbar-title>
          <v-btn-toggle v-model="layout" mandatory density="compact" divided>
            <v-btn value="list" size="small">List</v-btn>
            <v-btn value="graph" size="small">Graph</v-btn>
          </v-btn-toggle>
        </v-toolbar>

        <WorkflowGraph
          v-if="layout === 'graph'"
          :cards="current.cards"
          :relationships="current.relationships"
          @select="selectedCardId = $event"
        />

        <div v-else class="board-list pa-2">
          <section
            v-for="group in groups"
            :key="group.state"
            class="mb-4"
            :aria-label="group.label"
          >
            <h3 class="text-subtitle-2 mb-1">
              {{ group.label }} ({{ group.cards.length }})
            </h3>
            <v-list nav density="compact">
              <v-list-item
                v-for="card in group.cards"
                :key="card.id"
                :active="card.id === selectedCardId"
                :title="card.title"
                :subtitle="
                  card.owner?.label ?? card.waiting_reason ?? undefined
                "
                @click="selectedCardId = card.id"
              />
            </v-list>
          </section>
        </div>
      </template>
      <v-alert v-else type="info" density="compact" variant="tonal">
        Select a workflow to view its board.
      </v-alert>
    </div>

    <aside v-if="selectedCard" class="board-detail" aria-label="Card detail">
      <WorkCardDetail :card="selectedCard" />
    </aside>
  </div>
</template>

<style scoped>
.board-root {
  height: 100%;
}
.board-sidebar {
  width: 280px;
  flex: none;
  overflow-y: auto;
  border-right: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}
.board-main {
  flex: 1 1 auto;
  overflow-y: auto;
  min-width: 0;
}
.board-detail {
  width: 360px;
  flex: none;
  overflow-y: auto;
  border-left: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}
</style>

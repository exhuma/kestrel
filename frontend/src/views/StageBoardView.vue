<script setup lang="ts">
// The default surface (FR-009): every ingested request as one card,
// grouped into the six derived stage columns (FR-001). Replaces the old
// nav-list + selected-workflow layout in `WorkBoard.vue`.
import { computed, onMounted, onUnmounted } from 'vue'
import { useBoard } from '../composables/useBoard'
import { groupByStage } from '../lib/stages'
import StageColumn from '../components/board/StageColumn.vue'

const { workflows, error, refresh, startList, stopList } = useBoard()

onMounted(() => {
  void refresh()
  startList()
})
onUnmounted(() => {
  stopList()
})

const columns = computed(() => groupByStage(workflows.value))
const isEmpty = computed(() => workflows.value.length === 0)
</script>

<template>
  <div class="stage-board pa-2">
    <v-alert v-if="error" type="error" density="compact" class="mb-2">
      {{ error }}
    </v-alert>

    <v-empty-state
      v-if="isEmpty && !error"
      icon="$radar"
      title="No requests yet"
      text="Ingested requests will appear here as soon as one arrives."
    />

    <!-- Named custom-CSS gap: horizontal scroll and flex sizing of the
         column track (research R8) — Vuetify has no such primitive. -->
    <div v-else class="stage-column-track">
      <StageColumn
        v-for="column in columns"
        :key="column.stage"
        :stage="column.stage"
        :requests="column.requests"
      />
    </div>
  </div>
</template>

<style scoped>
.stage-board {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.stage-column-track {
  flex: 1 1 auto;
  display: flex;
  gap: 8px;
  overflow-x: auto;
  overflow-y: hidden;
  min-height: 0;
}
</style>

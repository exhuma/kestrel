<script setup lang="ts">
// One stage column: a sticky header naming the stage and its count, over
// a bounded, independently scrolling list of request cards. Sticky
// headers and the column's own scroll region are a named custom-CSS gap
// (research R8) — Vuetify has no column-track primitive for this.
import RequestCard from './RequestCard.vue'
import type { BoardRequest } from '../../lib/stages'

defineProps<{
  stage: string
  requests: BoardRequest[]
}>()
</script>

<template>
  <v-sheet class="stage-column d-flex flex-column" rounded border>
    <div class="stage-column-header pa-2 text-subtitle-2 d-flex align-center">
      <span>{{ stage }}</span>
      <v-chip size="small" class="ml-2">{{ requests.length }}</v-chip>
    </div>
    <div class="stage-column-body flex-grow-1 pa-2 pt-0">
      <RequestCard
        v-for="request in requests"
        :key="request.summary.id"
        :request="request"
      />
    </div>
  </v-sheet>
</template>

<style scoped>
.stage-column {
  width: 280px;
  flex: none;
  max-height: 100%;
  overflow: hidden;
}
.stage-column-header {
  position: sticky;
  top: 0;
  z-index: 1;
  background: rgb(var(--v-theme-surface));
  border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}
.stage-column-body {
  overflow-y: auto;
}
</style>

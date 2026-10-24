<script setup lang="ts">
// Thin route wrapper around the existing agent-session debug panel
// (FR-047). The view toggle that reached this is gone with the nav
// list — this route is its only remaining reachability, so its lazy
// load (a separate on-demand chunk) is preserved here rather than lost.
import { defineAsyncComponent } from 'vue'
import PanelLoading from '../components/PanelLoading.vue'
import PanelError from '../components/PanelError.vue'

const SessionPanel = defineAsyncComponent({
  loader: () => import('../components/SessionPanel.vue'),
  loadingComponent: PanelLoading,
  errorComponent: PanelError,
  delay: 200,
})
</script>

<template>
  <SessionPanel />
</template>

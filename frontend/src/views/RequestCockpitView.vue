<script setup lang="ts">
// Placeholder route target (GitHub #58 / User Story 2 builds the real
// cockpit: spine, narrative feed, artifact rail, action banner). Exists
// now only so the router's `cockpit` route resolves — every board card
// already links here (FR-028).
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <div class="pa-6">
    <v-alert type="info" variant="tonal" title="Request cockpit is coming">
      The detailed view for request <code>{{ route.params.id }}</code> is not
      built yet — see GitHub issue #58.
    </v-alert>
    <v-btn :to="{ name: 'board' }" variant="text" class="mt-4">
      Back to board
    </v-btn>
  </div>
</template>

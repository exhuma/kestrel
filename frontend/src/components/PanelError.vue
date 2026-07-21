<script setup lang="ts">
// Error affordance shown when an on-demand panel chunk fails to download
// (offline / transient network error). FR-009 requires a clear error here
// rather than a blank view or silent failure.
</script>

<template>
  <div class="d-flex justify-center align-center pa-6" style="height: 100%">
    <v-alert
      type="error"
      variant="tonal"
      title="Couldn’t load this view"
      max-width="480"
    >
      Its code failed to download. Check your connection and reload to try
      again.
    </v-alert>
  </div>
</template>

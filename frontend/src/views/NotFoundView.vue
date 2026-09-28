<script setup lang="ts">
// The catch-all route's surface, and the target for an unknown request
// id (FR-030): an explanatory message and a route back to the board,
// never a blank page or a raw error.
</script>

<template>
  <div
    class="d-flex flex-column justify-center align-center pa-6"
    style="height: 100%"
  >
    <v-alert
      type="warning"
      variant="tonal"
      title="Nothing here"
      max-width="480"
    >
      That address doesn't match anything in kestrel.
    </v-alert>
    <v-btn :to="{ name: 'board' }" variant="text" class="mt-4">
      Back to board
    </v-btn>
  </div>
</template>

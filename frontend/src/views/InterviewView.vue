<script setup lang="ts">
// Placeholder route target (GitHub #59 / User Story 3 builds the real
// interview workspace). Exists now only so the router's `interview`
// route resolves (FR-028).
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <div class="pa-6">
    <v-alert type="info" variant="tonal" title="Interview workspace is coming">
      The interview surface for request <code>{{ route.params.id }}</code> is
      not built yet — see GitHub issue #59.
    </v-alert>
    <v-btn
      :to="{ name: 'cockpit', params: { id: route.params.id } }"
      variant="text"
      class="mt-4"
    >
      Back to cockpit
    </v-btn>
  </div>
</template>

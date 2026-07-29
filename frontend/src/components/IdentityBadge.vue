<script setup lang="ts">
import { computed } from 'vue'
import { useIdentity } from '../composables/useIdentity'

// oauth2-proxy sits in front of kestrel and forwards the authenticated
// identity via request headers; the backend reflects those back verbatim.
// Kestrel performs no authentication of its own, so this is purely
// informational — hidden entirely when no proxy is in front (local dev).
const { identity } = useIdentity()

const displayName = computed(
  () =>
    identity.value?.preferred_username ||
    identity.value?.username ||
    identity.value?.email ||
    '',
)
</script>

<template>
  <v-tooltip v-if="displayName" :text="identity?.email || displayName">
    <template #activator="{ props }">
      <v-chip
        v-bind="props"
        variant="tonal"
        label
        class="me-2"
        prepend-icon="$account"
      >
        {{ displayName }}
      </v-chip>
    </template>
  </v-tooltip>
</template>

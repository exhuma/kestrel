<script setup lang="ts">
import SessionPanel from './components/SessionPanel.vue'
</script>

<template>
  <v-app>
    <v-app-bar color="primary" title="kestrel">
      <template #prepend>
        <img src="/logo.svg" alt="kestrel logo" height="40" class="ms-2" />
      </template>
    </v-app-bar>
    <v-main>
      <SessionPanel />
    </v-main>
  </v-app>
</template>

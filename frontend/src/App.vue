<script setup lang="ts">
import SessionPanel from './components/SessionPanel.vue'
</script>

<template>
  <v-app>
    <v-app-bar color="primary" title="agent-dispatcher" />
    <v-main>
      <SessionPanel />
    </v-main>
  </v-app>
</template>

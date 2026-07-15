<script setup lang="ts">
// Two-pane console shell shared by WorkflowPanel and SessionPanel: a fixed
// navigation rail on the left and the main stage on the right. Extracted after
// both panels existed (rule-of-two), so it captures exactly the duplicated
// layout scaffold and nothing speculative. Rail content goes in the `rail`
// slot; the stage is the default slot.
</script>

<template>
  <v-layout class="fill-height">
    <v-navigation-drawer permanent width="340">
      <slot name="rail" />
    </v-navigation-drawer>
    <v-main class="console-stage d-flex flex-column">
      <slot />
    </v-main>
  </v-layout>
</template>

<style scoped>
/* Let the stage own the remaining height with its own inner scroll region. */
.console-stage {
  min-height: 0;
}
</style>

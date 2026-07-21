<script setup lang="ts">
// Loading affordance shown while an on-demand panel chunk is being fetched
// (FR-009). Centered indeterminate spinner filling the stage area so a
// non-instant fetch never shows a blank view.
</script>

<template>
  <div class="d-flex justify-center align-center" style="height: 100%">
    <v-progress-circular indeterminate color="primary" />
  </div>
</template>

<script setup lang="ts">
// One line saying what a request is doing right now (feature 033): who
// is working on what, what it waits for, or what went wrong — never
// "working" once nothing is (the backend only reports live work).
import { computed } from 'vue'
import { describeActivity } from '../../lib/activity'
import { useNow } from '../../composables/useNow'
import type { RequestActivity } from '../../types/workflows'

const props = defineProps<{ activity: RequestActivity | null }>()

const now = useNow()
const view = computed(() =>
  props.activity ? describeActivity(props.activity, now.value) : null,
)
const color = computed(() =>
  view.value && view.value.tone !== 'default' ? view.value.tone : undefined,
)
const icon = computed(() => {
  if (!view.value || view.value.busy) return undefined
  if (view.value.tone === 'error' || view.value.tone === 'warning') {
    return '$alertCircle'
  }
  return view.value.tone === 'success' ? '$checkCircle' : '$circleOutline'
})
</script>

<template>
  <div
    v-if="view"
    class="d-flex align-center ga-2 text-body-2"
    :class="color ? `text-${color}` : 'text-medium-emphasis'"
    data-testid="activity-line"
    role="status"
  >
    <v-progress-circular v-if="view.busy" indeterminate size="14" width="2" />
    <v-icon v-else-if="icon" :icon="icon" size="small" />
    <span>{{ view.text }}</span>
  </div>
</template>

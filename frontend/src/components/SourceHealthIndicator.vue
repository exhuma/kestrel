<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive } from 'vue'
import { useSourceHealth } from '../composables/useSourceHealth'
import type { HealthState } from '../types/health'

const { items, refresh, recheck, start, stop } = useSourceHealth()

onMounted(() => {
  // Reliable baseline via plain fetch, independent of the SSE stream
  // actually connecting — see WorkflowPanel.vue for the same pattern.
  void refresh()
  start()
})
onUnmounted(stop)

// A name is "pending" from the moment its refresh is clicked until the
// next push shows a different checked_at — the API's 202 doesn't wait
// for the check itself (contracts/health-api.md).
const pendingSince = reactive<Record<string, string | null>>({})

const pending = computed(
  () =>
    new Set(
      Object.keys(pendingSince).filter((name) => {
        const current = items.value.find((i) => i.name === name)
        return (
          current !== undefined && current.checked_at === pendingSince[name]
        )
      }),
    ),
)

async function onRecheck(name: string): Promise<void> {
  const current = items.value.find((i) => i.name === name)
  pendingSince[name] = current?.checked_at ?? null
  await recheck(name)
}

const worstState = computed<HealthState>(() => {
  if (items.value.some((i) => i.state === 'unhealthy')) return 'unhealthy'
  if (items.value.some((i) => i.state === 'unknown')) return 'unknown'
  return 'healthy'
})

const stateIcon: Record<HealthState, string> = {
  healthy: '$checkCircle',
  unhealthy: '$alertCircle',
  unknown: '$circleOutline',
}
const stateColor: Record<HealthState, string | undefined> = {
  healthy: 'success',
  unhealthy: 'error',
  unknown: undefined,
}
const stateLabel: Record<HealthState, string> = {
  healthy: 'healthy',
  unhealthy: 'unreachable',
  unknown: 'not yet checked',
}
</script>

<template>
  <v-menu
    v-if="items.length"
    location="bottom end"
    :close-on-content-click="false"
  >
    <template #activator="{ props }">
      <v-btn
        v-bind="props"
        variant="text"
        icon
        :aria-label="`Source health: ${stateLabel[worstState]}`"
        :title="`Source health: ${stateLabel[worstState]}`"
      >
        <v-icon :icon="stateIcon[worstState]" :color="stateColor[worstState]" />
      </v-btn>
    </template>

    <v-list width="280">
      <v-list-subheader>Source health</v-list-subheader>
      <v-list-item v-for="h in items" :key="h.name">
        <template #prepend>
          <v-icon
            :icon="stateIcon[h.state]"
            :color="stateColor[h.state]"
            size="small"
          />
        </template>
        <v-list-item-title class="text-capitalize">{{
          h.name
        }}</v-list-item-title>
        <v-list-item-subtitle>{{ stateLabel[h.state] }}</v-list-item-subtitle>
        <template #append>
          <v-btn
            icon="$refresh"
            variant="text"
            size="small"
            :disabled="pending.has(h.name)"
            :aria-label="`Recheck ${h.name}`"
            @click="onRecheck(h.name)"
          />
        </template>
      </v-list-item>
    </v-list>
  </v-menu>
</template>

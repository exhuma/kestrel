<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useNotifications } from '../composables/useNotifications'

const emit = defineEmits<{ navigate: [workflowId: string] }>()
const {
  items,
  actionRequired,
  summaries,
  actionRequiredCount,
  refresh,
  markRead,
  start,
  stop,
} = useNotifications()

onMounted(() => {
  // Reliable baseline via plain fetch, independent of the SSE stream
  // actually connecting.
  void refresh()
  start()
})
onUnmounted(stop)

async function onClick(id: number, workflowId: string): Promise<void> {
  await markRead(id)
  emit('navigate', workflowId)
}
</script>

<template>
  <v-menu location="bottom end" :close-on-content-click="false">
    <template #activator="{ props }">
      <v-btn
        v-bind="props"
        variant="text"
        :aria-label="
          actionRequiredCount
            ? `Notifications, ${actionRequiredCount} needing action`
            : 'Notifications'
        "
      >
        <v-badge
          :model-value="actionRequiredCount > 0"
          :content="actionRequiredCount"
          color="error"
        >
          <v-icon icon="$bell" />
        </v-badge>
      </v-btn>
    </template>

    <v-list width="340" max-height="400">
      <v-list-item v-if="!items.length" class="text-medium-emphasis">
        No notifications yet
      </v-list-item>

      <template v-if="actionRequired.length">
        <v-list-subheader>Needs your action</v-list-subheader>
        <v-list-item
          v-for="n in actionRequired"
          :key="n.id"
          :title="n.message"
          :subtitle="new Date(n.created_at).toLocaleString()"
          @click="onClick(n.id, n.workflow_id)"
        >
          <template #prepend>
            <v-icon
              :icon="n.read ? '$circleOutline' : '$circle'"
              :color="n.read ? undefined : 'primary'"
              size="x-small"
            />
          </template>
        </v-list-item>
      </template>

      <template v-if="summaries.length">
        <v-list-subheader>Recent activity</v-list-subheader>
        <v-list-item
          v-for="n in summaries"
          :key="n.id"
          :title="n.message"
          :subtitle="new Date(n.created_at).toLocaleString()"
          @click="onClick(n.id, n.workflow_id)"
        >
          <template #prepend>
            <v-icon
              :icon="n.read ? '$circleOutline' : '$circle'"
              :color="n.read ? undefined : 'primary'"
              size="x-small"
            />
          </template>
        </v-list-item>
      </template>
    </v-list>
  </v-menu>
</template>

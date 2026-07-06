<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useNotifications } from '../composables/useNotifications'
import { useWorkflows } from '../composables/useWorkflows'

const emit = defineEmits<{ navigate: [] }>()
const {
  items,
  actionRequired,
  summaries,
  actionRequiredCount,
  markRead,
  start,
  stop,
} = useNotifications()
const { select } = useWorkflows()
const open = ref(false)

onMounted(start)
onUnmounted(stop)

async function onClick(id: number, workflowId: string): Promise<void> {
  await markRead(id)
  select(workflowId)
  open.value = false
  emit('navigate')
}
</script>

<template>
  <div class="notif">
    <button class="notif__bell" @click="open = !open"
      :aria-label="actionRequiredCount
        ? `Notifications, ${actionRequiredCount} needing action`
        : 'Notifications'">
      <span aria-hidden="true">🔔</span>
      <span v-if="actionRequiredCount" class="notif__badge mono">
        {{ actionRequiredCount }}
      </span>
    </button>
    <div v-if="open" class="notif__panel">
      <p v-if="!items.length" class="notif__empty mono">No notifications yet</p>
      <template v-if="actionRequired.length">
        <p class="notif__section mono">Needs your action</p>
        <button v-for="n in actionRequired" :key="n.id" class="notif__item"
          :class="{ 'notif__item--unread': !n.read }"
          @click="onClick(n.id, n.workflow_id)">
          <span class="notif__msg">{{ n.message }}</span>
          <span class="notif__time mono">
            {{ new Date(n.created_at).toLocaleString() }}
          </span>
        </button>
      </template>
      <template v-if="summaries.length">
        <p class="notif__section mono">Recent activity</p>
        <button v-for="n in summaries" :key="n.id" class="notif__item"
          :class="{ 'notif__item--unread': !n.read }"
          @click="onClick(n.id, n.workflow_id)">
          <span class="notif__msg">{{ n.message }}</span>
          <span class="notif__time mono">
            {{ new Date(n.created_at).toLocaleString() }}
          </span>
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.notif { position: relative; }
.notif__bell {
  position: relative; background: none; border: 1px solid var(--line);
  border-radius: 999px; width: 34px; height: 34px; cursor: pointer;
  color: var(--text-hi); font-size: 15px; display: grid; place-items: center;
}
.notif__bell:hover { border-color: var(--idle); background: var(--ink-700); }
.notif__badge {
  position: absolute; top: -4px; right: -4px; background: var(--err);
  color: var(--ink-900); font-size: 10px; font-weight: 700; border-radius: 999px;
  min-width: 16px; height: 16px; display: grid; place-items: center; padding: 0 3px;
}
.notif__panel {
  position: absolute; top: 42px; right: 0; width: 320px; max-height: 360px;
  overflow-y: auto; background: var(--ink-800); border: 1px solid var(--line);
  border-radius: var(--r-md); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35); z-index: 20;
}
.notif__empty { padding: 14px; color: var(--text-dim); font-size: 12px; }
.notif__section {
  padding: 8px 14px 4px; margin: 0; font-size: 10px; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--text-dim);
  border-bottom: 1px solid var(--line-soft); background: var(--ink-900);
}
.notif__item {
  display: flex; flex-direction: column; gap: 3px; width: 100%; text-align: left;
  background: none; border: none; border-bottom: 1px solid var(--line-soft);
  padding: 10px 14px; cursor: pointer; color: var(--text-mid);
}
.notif__item:hover { background: var(--ink-700); }
.notif__item--unread { color: var(--text-hi); }
.notif__item--unread .notif__msg::before { content: '● '; color: var(--signal); }
.notif__msg { font-size: 12.5px; }
.notif__time { font-size: 10.5px; color: var(--text-dim); }
</style>

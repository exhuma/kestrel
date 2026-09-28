<script setup lang="ts">
// The rail says **what** the request produced (FR-014): the durable set,
// in pipeline order, including the entries not yet reached. Opening one
// shows its content in `ArtifactDialog`.
import { computed, ref } from 'vue'
import { railItems, type ArtifactRailItem } from '../../lib/artifacts'
import type { WorkCardSummary } from '../../types/workflows'
import ArtifactDialog from './ArtifactDialog.vue'

const props = defineProps<{ cards: WorkCardSummary[] }>()

const items = computed(() => railItems(props.cards))

const openItem = ref<ArtifactRailItem | null>(null)

/** Theme colour per state; unproduced entries stay neutral so the rail
 *  reads as a plan rather than as a list of problems. */
const STATE_COLORS: Readonly<Record<string, string>> = {
  'Awaiting your decision': 'warning',
  Quarantined: 'error',
  Failed: 'error',
  Cancelled: 'error',
  Rejected: 'warning',
  Approved: 'success',
  Produced: 'success',
}

function stateColor(state: string): string | undefined {
  return STATE_COLORS[state]
}

function open(item: ArtifactRailItem): void {
  if (item.available) openItem.value = item
}
</script>

<template>
  <v-sheet class="pa-2" rounded>
    <div class="text-subtitle-2 px-2 py-1">Artifacts</div>
    <v-list density="compact" nav>
      <v-list-item
        v-for="item in items"
        :key="item.kind"
        :prepend-icon="item.icon"
        :title="item.label"
        :disabled="!item.available"
        :active="openItem?.kind === item.kind"
        @click="open(item)"
      >
        <template #append>
          <v-chip
            size="x-small"
            variant="tonal"
            :color="stateColor(item.state)"
          >
            {{ item.state }}
          </v-chip>
        </template>
      </v-list-item>
    </v-list>

    <ArtifactDialog
      :artifact-id="openItem?.artifactId ?? null"
      :label="openItem?.label ?? ''"
      @close="openItem = null"
    />
  </v-sheet>
</template>

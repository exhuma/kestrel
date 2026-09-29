<script setup lang="ts">
// The operator's own work on this request (feature 031, FR-010): the
// tasks CAB-2 approved as manual, which no agent will ever pick up.
// Kept apart from the action banner on purpose: a manual task can take
// days, and the banner is reserved for the one decision pending now
// (feature 029 FR-016). Renders nothing when the request has none.
import { computed, ref } from 'vue'
import { useBoard } from '../../composables/useBoard'
import type { CardState, WorkCardSummary } from '../../types/workflows'
import ArtifactDialog from './ArtifactDialog.vue'

const props = defineProps<{ cards: WorkCardSummary[] }>()

const { applyIntervention } = useBoard()

const tasks = computed(() =>
  props.cards.filter((c) => c.card_type === 'manual_task'),
)

const STATE_LABEL: Partial<Record<CardState, string>> = {
  awaiting_human: 'To do',
  waiting_dependency: 'Waiting on earlier work',
  done: 'Done',
  cancelled: 'Cancelled',
}

function stateLabel(card: WorkCardSummary): string {
  return STATE_LABEL[card.state] ?? card.state
}

function canComplete(card: WorkCardSummary): boolean {
  return card.allowed_actions.includes('complete_manual_task')
}

const reading = ref<WorkCardSummary | null>(null)
const busyId = ref<string | null>(null)

async function complete(card: WorkCardSummary): Promise<void> {
  busyId.value = card.id
  try {
    await applyIntervention(card.id, 'complete_manual_task')
  } finally {
    busyId.value = null
  }
}
</script>

<template>
  <v-card v-if="tasks.length" variant="outlined">
    <v-card-title class="text-subtitle-1">Your manual tasks</v-card-title>
    <v-list density="compact">
      <v-list-item
        v-for="card in tasks"
        :key="card.id"
        :title="card.title"
        :subtitle="stateLabel(card)"
        prepend-icon="$account"
      >
        <template #append>
          <v-btn
            v-if="card.latest_artifact"
            variant="text"
            size="small"
            @click="reading = card"
          >
            Read task
          </v-btn>
          <v-btn
            v-if="canComplete(card)"
            variant="tonal"
            color="primary"
            size="small"
            :loading="busyId === card.id"
            @click="complete(card)"
          >
            Mark done
          </v-btn>
        </template>
      </v-list-item>
    </v-list>
    <ArtifactDialog
      :artifact-id="reading?.latest_artifact?.id ?? null"
      :label="reading?.title ?? ''"
      @close="reading = null"
    />
  </v-card>
</template>

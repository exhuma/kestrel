<script setup lang="ts">
// Every card of the request, grouped by where it stands (feature 034,
// US3), so a count on the board ("2 cancelled") always has names and a
// cause behind it here. Groups that are over start collapsed; what is
// still moving starts open.
import { computed, ref, watch } from 'vue'
import { workGroups } from '../../lib/workList'
import type { BoardEvent, WorkCardSummary } from '../../types/workflows'

const props = defineProps<{
  cards: WorkCardSummary[]
  events: BoardEvent[]
}>()

const groups = computed(() => workGroups(props.cards, props.events))

const CLOSED = new Set(['done'])
const open = ref<string[]>([])
watch(
  () => groups.value.map((g) => g.key).join(),
  () => {
    open.value = groups.value
      .map((g) => g.key)
      .filter((key) => !CLOSED.has(key))
  },
  { immediate: true },
)
</script>

<template>
  <v-card v-if="groups.length" id="work" variant="outlined">
    <v-card-title class="text-subtitle-1">Work on this request</v-card-title>
    <v-expansion-panels v-model="open" multiple variant="accordion" flat>
      <v-expansion-panel
        v-for="group in groups"
        :key="group.key"
        :value="group.key"
        :data-testid="`work-group-${group.key}`"
      >
        <v-expansion-panel-title>
          {{ group.label }} ({{ group.items.length }})
        </v-expansion-panel-title>
        <v-expansion-panel-text>
          <v-list density="compact">
            <v-list-item
              v-for="item in group.items"
              :key="item.card.id"
              :title="item.card.title"
            >
              <v-list-item-subtitle v-if="item.role">
                {{ item.role }}
              </v-list-item-subtitle>
              <v-list-item-subtitle v-if="item.waitsOn" data-testid="waits-on">
                Waiting on {{ item.waitsOn }}
              </v-list-item-subtitle>
              <v-list-item-subtitle
                v-if="item.endedBecause"
                data-testid="ended-because"
              >
                {{ item.endedBecause }}
              </v-list-item-subtitle>
            </v-list-item>
          </v-list>
        </v-expansion-panel-text>
      </v-expansion-panel>
    </v-expansion-panels>
  </v-card>
</template>

<script setup lang="ts">
// One narrative-feed row: who, when, and what happened. The neutral
// persona is rendered by name ("System"), never as an empty attribution
// (FR-013).
import { computed } from 'vue'
import { personaInitial, personaName, type FeedEntry } from '../../lib/personas'

const props = defineProps<{ entry: FeedEntry }>()

const name = computed(() => personaName(props.entry.persona))
const initial = computed(() => personaInitial(props.entry.persona))

/** The operator's own actions are coloured as the operator, not as the
 *  tone of the outcome, so "what I did" stays visually distinct from
 *  "what happened to the request". */
const avatarColor = computed(() =>
  props.entry.persona.kind === 'operator' ? 'primary' : 'surface-variant',
)
</script>

<template>
  <div class="d-flex align-start ga-3">
    <v-avatar size="28" :color="avatarColor">
      <span class="text-caption">{{ initial }}</span>
    </v-avatar>
    <div class="flex-1-1">
      <div class="d-flex align-center ga-2 flex-wrap">
        <span class="text-body-2 font-weight-medium">{{ name }}</span>
        <span class="text-caption text-medium-emphasis">
          {{ entry.timestamp }}
        </span>
      </div>
      <div class="text-body-2">{{ entry.summary }}</div>
      <div
        v-if="entry.event.payload"
        class="feed-payload text-caption text-medium-emphasis"
      >
        {{ entry.event.payload }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.feed-payload {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>

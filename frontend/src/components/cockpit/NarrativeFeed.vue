<script setup lang="ts">
// The feed says **why** the request got where it is (FR-012): every event
// in order, attributed to a persona. Monitoring only — nothing here is
// answerable, every answer-shaped interaction leaves for the interview
// view (FR-017).
//
// Reuses SessionPanel's feed idiom rather than inventing a second one:
// a compact `v-timeline`, a tone-coloured dot per row, and auto-scroll on
// new events.
import { computed, ref, watch, nextTick } from 'vue'
import { toFeedEntries, type FeedTone } from '../../lib/personas'
import type { BoardEvent } from '../../types/workflows'
import FeedEntryRow from './FeedEntry.vue'

const props = defineProps<{ events: BoardEvent[] }>()

const entries = computed(() => toFeedEntries(props.events))

const TONE_COLORS: Readonly<Record<FeedTone, string | undefined>> = {
  info: undefined,
  success: 'success',
  warning: 'warning',
  error: 'error',
}

function toneColor(tone: FeedTone): string | undefined {
  return TONE_COLORS[tone]
}

const feedEl = ref<HTMLElement | null>(null)

/** Whether the operator is reading history rather than watching the live
 *  edge. Auto-scroll is suppressed while they are (FR-018): yanking them
 *  to the bottom mid-read is the behaviour this guards against. */
const pinnedToBottom = ref(true)
const NEAR_BOTTOM_PX = 48

function onScroll(): void {
  const el = feedEl.value
  if (!el) return
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  pinnedToBottom.value = distance <= NEAR_BOTTOM_PX
}

watch(
  () => props.events.length,
  async () => {
    if (!pinnedToBottom.value) return
    await nextTick()
    const el = feedEl.value
    if (el) el.scrollTop = el.scrollHeight
  },
)
</script>

<template>
  <div ref="feedEl" class="narrative-feed pa-2" @scroll="onScroll">
    <v-empty-state
      v-if="entries.length === 0"
      icon="$radar"
      headline="Nothing has happened yet"
      text="This request's history will appear here as it progresses."
    />
    <v-timeline
      v-else
      density="compact"
      side="end"
      align="start"
      truncate-line="both"
    >
      <v-timeline-item
        v-for="(entry, i) in entries"
        :key="i"
        size="x-small"
        :dot-color="toneColor(entry.tone)"
      >
        <FeedEntryRow :entry="entry" />
      </v-timeline-item>
    </v-timeline>
  </div>
</template>

<style scoped>
/* Named custom-CSS gap (research R8): an independent, bounded scroll
   region. Vuetify has no component for "this pane scrolls on its own
   within a shared viewport", and the feed must scroll without taking the
   spine and rail with it. */
.narrative-feed {
  overflow-y: auto;
  height: 100%;
}
</style>

<script setup lang="ts">
// One request, scoped entirely to itself (FR-010). Its regions each
// answering a different question:
//
//   banner — what does this want from me?   (the most important)
//   spine  — where is it?
//   work   — what is it made of, and what ended how?
//   feed   — why did it get here?
//   rail   — what has it produced?
//
// The composition is the whole job of this file: the regions own their own
// behaviour, and everything derived lives in `lib/`.
import { computed, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useBoard } from '../composables/useBoard'
import { useBoardEvents } from '../composables/useBoardEvents'
import NotFoundView from './NotFoundView.vue'
import ActionBanner from '../components/cockpit/ActionBanner.vue'
import PhaseSpine from '../components/cockpit/PhaseSpine.vue'
import NarrativeFeed from '../components/cockpit/NarrativeFeed.vue'
import ArtifactRail from '../components/cockpit/ArtifactRail.vue'
import ManualTaskList from '../components/cockpit/ManualTaskList.vue'
import WorkList from '../components/cockpit/WorkList.vue'
import ActivityLine from '../components/common/ActivityLine.vue'

const route = useRoute()
const { current, error, loading, select, stop } = useBoard()
const { events, start: startEvents, stop: stopEvents } = useBoardEvents()

const workflowId = computed(() => String(route.params.id ?? ''))

/** `useBoard` keeps the previous snapshot until the new one lands, so the
 *  cockpit must check the snapshot it renders is the one it asked for —
 *  otherwise it would briefly show the last request's story under this
 *  request's address. */
const snapshot = computed(() =>
  current.value?.id === workflowId.value ? current.value : null,
)

/** An unknown id is not an error to apologise for — it gets the
 *  explanatory surface with a route back (FR-030). */
const isUnknown = computed(() => error.value?.includes('404') === true)

watch(
  workflowId,
  (id) => {
    if (!id) return
    void select(id)
    startEvents(id)
  },
  { immediate: true },
)

onUnmounted(() => {
  stop()
  stopEvents()
})
</script>

<template>
  <NotFoundView v-if="isUnknown" />

  <div v-else class="cockpit pa-4">
    <v-alert v-if="error" type="error" class="mb-4">
      {{ error }}
      <template #append>
        <v-btn :to="{ name: 'board' }" variant="text">Back to board</v-btn>
      </template>
    </v-alert>

    <v-progress-linear v-if="loading && !snapshot" indeterminate />

    <template v-if="snapshot">
      <div class="mb-4">
        <div class="text-h6">{{ snapshot.title }}</div>
        <div class="text-caption text-medium-emphasis">
          {{ snapshot.task_label }}
        </div>
        <ActivityLine :activity="snapshot.activity" class="mt-1" />
      </div>

      <ActionBanner
        class="mb-4"
        :cards="snapshot.cards"
        :workflow-id="workflowId"
      />

      <v-sheet class="pa-2 mb-4" rounded>
        <PhaseSpine :phase="snapshot.phase" :phases="snapshot.phases" />
      </v-sheet>

      <ManualTaskList class="mb-4" :cards="snapshot.cards" />

      <WorkList class="mb-4" :cards="snapshot.cards" :events="events" />

      <div class="cockpit__panes d-flex ga-4">
        <v-sheet class="cockpit__feed flex-1-1" rounded>
          <NarrativeFeed :events="events" />
        </v-sheet>
        <div class="cockpit__rail">
          <ArtifactRail
            :cards="snapshot.cards"
            :task-body="snapshot.task_body"
            :change-request-url="snapshot.change_request_url"
          />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* Named custom-CSS gap (research R8): independent per-pane scroll
   regions. The feed and the rail each scroll within the viewport rather
   than scrolling the whole page, so the banner and spine stay in view
   while reading a long history. Vuetify has no component for this. */
.cockpit {
  height: 100%;
  overflow-y: auto;
}
.cockpit__panes {
  align-items: stretch;
  min-height: 0;
}
.cockpit__feed {
  min-width: 0;
  max-height: 60vh;
  overflow: hidden;
}
.cockpit__rail {
  flex: 0 0 320px;
  max-height: 60vh;
  overflow-y: auto;
}
</style>

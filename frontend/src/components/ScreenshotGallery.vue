<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { API_BASE } from '../api'
import { useScreenshots } from '../composables/useScreenshots'

const props = defineProps<{
  workflowId: string
  stage: 'refine' | 'verify'
  /** Bumped as the run progresses so newly-captured shots get re-fetched. */
  revision?: string | number
}>()

const { shots, load } = useScreenshots()
const lightboxSrc = ref<string | null>(null)

const staged = computed(() =>
  shots.value.filter((s) => s.stage === props.stage),
)

// Absolute src for a backend-served image (cross-origin, no auth needed).
function imageSrc(url: string): string {
  return `${API_BASE}${url}`
}

// Re-load on the run or its revision changing (e.g. a new verify round),
// so shots appear without a manual reload but without polling either.
watch(
  () => [props.workflowId, props.revision],
  () => {
    if (props.workflowId) void load(props.workflowId)
  },
  { immediate: true },
)
</script>

<template>
  <div v-if="staged.length" class="mt-3">
    <div class="text-overline text-medium-emphasis mb-1">
      {{ stage === 'refine' ? 'Mockups' : 'Screenshots' }}
    </div>
    <div class="d-flex flex-wrap ga-2">
      <v-img
        v-for="shot in staged"
        :key="shot.name"
        :src="imageSrc(shot.url)"
        :alt="shot.name"
        width="160"
        height="120"
        cover
        class="rounded border shot"
        @click="lightboxSrc = imageSrc(shot.url)"
      />
    </div>
    <v-dialog
      :model-value="lightboxSrc !== null"
      max-width="900"
      @update:model-value="lightboxSrc = null"
    >
      <v-img :src="lightboxSrc ?? ''" />
    </v-dialog>
  </div>
</template>

<style scoped>
.shot {
  cursor: pointer;
}
</style>

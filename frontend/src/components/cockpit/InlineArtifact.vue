<script setup lang="ts">
// An artifact's text shown in place, for content short enough to read
// where the decision is taken — pm's restatement of the request on the
// understanding gate (feature 032, #67). Rendered as text, never as
// HTML: it is agent output crossing into the browser.
import { ref, watch } from 'vue'
import { api } from '../../api'
import type { BoardArtifactContent } from '../../types/workflows'

const props = defineProps<{ artifactId: string }>()

const text = ref<string | null>(null)
const failed = ref(false)

async function load(id: string): Promise<void> {
  text.value = null
  failed.value = false
  try {
    const content = await api.get<BoardArtifactContent>(
      `/api/board/artifacts/${id}/content`,
    )
    text.value = content.content
  } catch {
    failed.value = true
  }
}

watch(() => props.artifactId, load, { immediate: true })
</script>

<template>
  <div data-testid="inline-artifact">
    <div v-if="text !== null" class="text-body-2 text-pre-wrap">
      {{ text }}
    </div>
    <div v-else-if="failed" class="text-caption">
      Could not load it. Try again shortly.
    </div>
    <v-progress-linear v-else indeterminate />
  </div>
</template>

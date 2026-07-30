<script setup lang="ts">
import { ref } from 'vue'
import { API_BASE } from '../api'
import type { Mockup } from '../types/questionnaire'

defineProps<{
  /** Mockups for this round. */
  mockups: Mockup[]
  /** Current feedback text keyed by mockup name. */
  feedback: Record<string, string>
}>()
const emit = defineEmits<{
  'update:feedback': [name: string, text: string]
}>()

const lightboxSrc = ref<string | null>(null)

// Absolute src for a backend-served image (cross-origin, no auth needed).
function imageSrc(url: string): string {
  return `${API_BASE}${url}`
}
</script>

<template>
  <div class="mb-4">
    <div class="text-overline text-medium-emphasis mb-1">Proposed mockups</div>
    <div class="d-flex flex-column ga-4">
      <div v-for="m in mockups" :key="m.name" class="d-flex ga-3 flex-wrap">
        <v-img
          :src="imageSrc(m.url)"
          :alt="m.name"
          width="220"
          height="150"
          cover
          class="rounded border shot"
          @click="lightboxSrc = imageSrc(m.url)"
        />
        <div class="mockup__body">
          <p v-if="m.explanation" class="text-body-2 mb-2">
            {{ m.explanation }}
          </p>
          <v-textarea
            :model-value="feedback[m.name] ?? ''"
            label="Feedback on this mockup (optional)…"
            data-testid="mockup-feedback"
            rows="2"
            auto-grow
            hide-details
            density="compact"
            @update:model-value="emit('update:feedback', m.name, $event)"
          />
        </div>
      </div>
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
.mockup__body {
  flex: 1 1 0;
  min-width: 240px;
}
</style>

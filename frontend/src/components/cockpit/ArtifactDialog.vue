<script setup lang="ts">
// One artifact's content, opened from the rail.
//
// Two safety rules, both FR-015: the content is agent output crossing
// into the browser, so it is rendered as *text* via interpolation and
// never as markup; and `trust` is always shown, so `agent_output` can
// never be mistaken for `operator_approved`.
//
// A second mode (feature 030) shows `directContent` handed in by the
// caller — the original request, which is no artifact and has no trust
// level. It fetches nothing and shows `note` where the chip would be,
// still rendered as text.
import { computed, ref, watch } from 'vue'
import { api } from '../../api'
import type { BoardArtifactContent } from '../../types/workflows'

const props = defineProps<{
  /** The artifact to show, or `null` when the dialog is closed. */
  artifactId: string | null
  /** The rail's label for it — the dialog's own title. */
  label: string
  /** Content to show as-is instead of fetching `artifactId`. */
  directContent?: string | null
  /** Shown with `directContent`, in place of the trust chip. */
  note?: string | null
}>()

const isDirect = computed(() => props.directContent != null)
const isOpen = computed(() => props.artifactId !== null || isDirect.value)

const emit = defineEmits<{ close: [] }>()

const content = ref<BoardArtifactContent | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)

/** Trust values other than an explicit operator approval are the norm,
 *  not an anomaly — so the chip states the level plainly rather than
 *  warning only on the untrusted case. */
function trustColor(trust: string): string {
  return trust === 'operator_approved' ? 'success' : 'warning'
}

async function load(id: string): Promise<void> {
  loading.value = true
  content.value = null
  error.value = null
  try {
    content.value = await api.get<BoardArtifactContent>(
      `/api/board/artifacts/${id}/content`,
    )
  } catch {
    error.value = 'Could not load this artifact.'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.artifactId,
  (id) => {
    if (id) void load(id)
    else content.value = null
  },
  { immediate: true },
)
</script>

<template>
  <v-dialog
    :model-value="isOpen"
    max-width="900"
    scrollable
    @update:model-value="emit('close')"
  >
    <v-card>
      <v-card-item>
        <v-card-title>{{ label }}</v-card-title>
        <template #append>
          <v-chip
            v-if="content && !isDirect"
            :color="trustColor(content.trust)"
            variant="tonal"
            data-testid="artifact-trust"
          >
            {{ content.trust }}
          </v-chip>
        </template>
      </v-card-item>

      <v-divider />

      <v-card-text>
        <template v-if="isDirect">
          <v-alert
            v-if="note"
            type="info"
            variant="tonal"
            density="compact"
            class="mb-3"
            data-testid="artifact-note"
          >
            {{ note }}
          </v-alert>
          <pre class="artifact-content text-body-2">{{ directContent }}</pre>
        </template>
        <v-progress-linear v-else-if="loading" indeterminate />
        <v-alert v-else-if="error" type="error">{{ error }}</v-alert>
        <pre v-else-if="content" class="artifact-content text-body-2">{{
          content.content
        }}</pre>
      </v-card-text>

      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="emit('close')">Close</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<style scoped>
.artifact-content {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  margin: 0;
}
</style>

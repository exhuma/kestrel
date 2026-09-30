<script setup lang="ts">
// Artifact or request text as the operator should read it (feature 043):
// structured data (JSON) stays preformatted, anything else is rendered
// as Markdown. `renderMarkdown` escapes raw HTML and drops unsafe links,
// so agent output never becomes live markup (FR-005) — that is what
// makes the `v-html` below safe.
import { computed } from 'vue'
import { isStructured, renderMarkdown } from '../../lib/markdown'

const props = defineProps<{
  text: string
  /** The artifact's media type, when known. */
  mimeType?: string | null
}>()

const structured = computed(() => isStructured(props.mimeType, props.text))
const html = computed(() =>
  structured.value ? '' : renderMarkdown(props.text),
)
</script>

<template>
  <pre
    v-if="structured"
    class="artifact-pre text-body-2"
    data-testid="artifact-text-pre"
    >{{ text }}</pre
  >
  <div
    v-else
    class="markdown text-body-2"
    data-testid="artifact-text-md"
    v-html="html"
  />
</template>

<style scoped>
.artifact-pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  margin: 0;
}
</style>

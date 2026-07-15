<script setup lang="ts">
import { ref } from 'vue'
import type { EventVM } from '../lib/eventView'

defineProps<{ event: EventVM }>()
const expanded = ref(false)
</script>

<template>
  <div class="ecard border-b py-1">
    <div class="d-flex align-start ga-2 text-body-2">
      <template v-if="event.view.kind === 'chat'">
        <span class="ecard__role text-medium-emphasis">{{
          event.view.role
        }}</span>
        <p class="ecard__text ma-0 flex-1-1">{{ event.view.text }}</p>
      </template>

      <template v-else-if="event.view.kind === 'tool_call'">
        <details class="ecard__tool flex-1-1">
          <summary class="text-warning">
            <v-icon icon="mdi-cog-outline" size="x-small" />
            {{ event.view.name }}
            <span v-if="event.view.input" class="text-medium-emphasis">
              · {{ event.view.input }}
            </span>
          </summary>
          <p v-if="event.view.preface" class="text-medium-emphasis ma-0 mt-1">
            {{ event.view.preface }}
          </p>
        </details>
      </template>

      <template v-else-if="event.view.kind === 'tool_result'">
        <v-icon
          icon="mdi-subdirectory-arrow-right"
          size="x-small"
          class="text-medium-emphasis mt-1"
        />
        <span
          class="ecard__text flex-1-1"
          :class="event.view.isError ? 'text-error' : 'text-medium-emphasis'"
        >
          {{
            event.view.content.length > 160
              ? `${event.view.content.slice(0, 160)}…`
              : event.view.content
          }}
        </span>
      </template>

      <template v-else-if="event.view.kind === 'thinking'">
        <v-chip size="x-small" variant="tonal">
          thinking… ~{{ event.view.tokens }} tok
        </v-chip>
      </template>

      <template v-else-if="event.view.kind === 'system'">
        <span class="text-medium-emphasis flex-1-1">{{
          event.view.summary
        }}</span>
      </template>

      <template v-else-if="event.view.kind === 'rate_limit'">
        <v-chip size="x-small" color="warning" variant="tonal">
          rate limit: {{ event.view.status }}
        </v-chip>
      </template>

      <template v-else-if="event.view.kind === 'result'">
        <v-alert
          :type="event.view.success ? 'success' : 'error'"
          density="compact"
          variant="tonal"
          class="flex-1-1"
        >
          <span>{{ event.view.success ? 'done' : 'failed' }}</span>
          <span v-if="event.view.durationMs" class="text-medium-emphasis">
            · {{ (event.view.durationMs / 1000).toFixed(1) }}s
          </span>
          <span v-if="event.view.summary"> · {{ event.view.summary }}</span>
        </v-alert>
      </template>

      <template v-else>
        <span class="text-primary flex-shrink-0">{{ event.type }}</span>
        <span class="ecard__text flex-1-1 text-medium-emphasis">
          {{ JSON.stringify(event.raw).slice(0, 140) }}
        </span>
      </template>

      <v-btn
        icon="mdi-code-json"
        size="x-small"
        variant="text"
        density="comfortable"
        :aria-label="expanded ? 'Hide raw JSON' : 'Show raw JSON'"
        @click="expanded = !expanded"
      />
    </div>
    <pre v-if="expanded" class="ecard__raw text-medium-emphasis">{{
      JSON.stringify(event.raw, null, 2)
    }}</pre>
  </div>
</template>

<style scoped>
.ecard__role {
  flex: none;
  width: 60px;
}
.ecard__text {
  white-space: pre-wrap;
  word-break: break-word;
}
.ecard__raw {
  margin: 6px 0 0;
  padding: 8px 10px;
  border-radius: 4px;
  background: rgb(var(--v-theme-surface-light));
  font-size: 11.5px;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>

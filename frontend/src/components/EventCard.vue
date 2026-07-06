<script setup lang="ts">
import { ref } from 'vue'
import type { EventVM } from '../lib/eventView'

defineProps<{ event: EventVM }>()
const expanded = ref(false)
</script>

<template>
  <div class="ecard" :class="`ecard--${event.view.kind}`">
    <div class="ecard__row">
      <template v-if="event.view.kind === 'chat'">
        <span class="ecard__role mono">{{ event.view.role }}</span>
        <p class="ecard__text">{{ event.view.text }}</p>
      </template>

      <template v-else-if="event.view.kind === 'tool_call'">
        <details class="ecard__tool">
          <summary>
            <span aria-hidden="true">⚙</span> {{ event.view.name }}
            <span v-if="event.view.input" class="mono ecard__tool-arg">
              · {{ event.view.input }}
            </span>
          </summary>
          <p v-if="event.view.preface" class="ecard__preface">
            {{ event.view.preface }}
          </p>
        </details>
      </template>

      <template v-else-if="event.view.kind === 'tool_result'">
        <span class="ecard__glyph" aria-hidden="true">↳</span>
        <span
          class="ecard__result-text mono"
          :class="{ 'ecard__result-text--err': event.view.isError }"
        >
          {{
            event.view.content.length > 160
              ? `${event.view.content.slice(0, 160)}…`
              : event.view.content
          }}
        </span>
      </template>

      <template v-else-if="event.view.kind === 'thinking'">
        <span class="chip t-sys mono"
          >thinking… ~{{ event.view.tokens }} tok</span
        >
      </template>

      <template v-else-if="event.view.kind === 'system'">
        <span class="ecard__sys mono">{{ event.view.summary }}</span>
      </template>

      <template v-else-if="event.view.kind === 'rate_limit'">
        <span class="chip t-warn mono"
          >rate limit: {{ event.view.status }}</span
        >
      </template>

      <template v-else-if="event.view.kind === 'result'">
        <div
          class="ecard__banner"
          :class="event.view.success ? 't-ok' : 't-err'"
        >
          <span>{{ event.view.success ? '✓ done' : '✕ failed' }}</span>
          <span v-if="event.view.durationMs" class="mono">
            {{ (event.view.durationMs / 1000).toFixed(1) }}s
          </span>
          <span v-if="event.view.summary" class="ecard__banner-text">
            {{ event.view.summary }}
          </span>
        </div>
      </template>

      <template v-else>
        <span class="ecard__type mono">{{ event.type }}</span>
        <span class="ecard__fallback mono">
          {{ JSON.stringify(event.raw).slice(0, 140) }}
        </span>
      </template>

      <button
        class="ecard__toggle mono"
        @click="expanded = !expanded"
        :aria-label="expanded ? 'Hide raw JSON' : 'Show raw JSON'"
      >
        { }
      </button>
    </div>
    <pre v-if="expanded" class="ecard__raw mono">{{
      JSON.stringify(event.raw, null, 2)
    }}</pre>
  </div>
</template>

<style scoped>
.ecard {
  padding: 6px 0;
  border-bottom: 1px solid var(--line-soft);
  font-size: 12.5px;
}
.ecard__row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.ecard__role {
  color: var(--text-dim);
  flex: none;
  width: 60px;
}
.ecard--chat .ecard__text {
  margin: 0;
  color: var(--text-hi);
  white-space: pre-wrap;
  flex: 1;
}
.ecard__tool {
  flex: 1;
  color: var(--text-mid);
}
.ecard__tool summary {
  cursor: pointer;
  color: var(--warn);
}
.ecard__tool-arg {
  color: var(--text-dim);
}
.ecard__preface {
  margin: 4px 0 0;
  color: var(--text-mid);
}
.ecard__glyph {
  color: var(--text-dim);
  flex: none;
}
.ecard__result-text {
  color: var(--text-mid);
  flex: 1;
}
.ecard__result-text--err {
  color: var(--err);
}
.ecard__sys {
  color: var(--text-dim);
  flex: 1;
}
.ecard__type {
  color: var(--signal);
  flex: none;
}
.ecard__fallback {
  color: var(--text-mid);
  flex: 1;
  word-break: break-word;
}
.ecard__banner {
  --c: var(--ok);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: var(--r-md);
  border: 1px solid color-mix(in srgb, var(--c) 40%, var(--line));
  background: color-mix(in srgb, var(--c) 10%, transparent);
  color: var(--c);
  flex: 1;
}
.ecard__banner.t-err {
  --c: var(--err);
}
.ecard__banner-text {
  color: var(--text-hi);
}
.ecard__toggle {
  flex: none;
  background: none;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: var(--r-sm);
  font-size: 10.5px;
  padding: 1px 6px;
  cursor: pointer;
}
.ecard__toggle:hover {
  color: var(--text-hi);
  border-color: var(--idle);
}
.ecard__raw {
  margin: 6px 0 0;
  padding: 8px 10px;
  background: var(--ink-750);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  color: var(--text-mid);
  font-size: 11.5px;
  white-space: pre-wrap;
  word-break: break-word;
}
.chip {
  --c: var(--idle);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 9px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--c) 40%, var(--line));
  background: color-mix(in srgb, var(--c) 12%, transparent);
  font-size: 11px;
  color: var(--c);
}
.chip.t-warn {
  --c: var(--warn);
}
.chip.t-sys {
  --c: var(--idle);
}
</style>

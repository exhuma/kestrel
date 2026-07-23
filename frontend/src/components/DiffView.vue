<script setup lang="ts">
import { computed } from 'vue'
import { useTheme } from 'vuetify'
import { html as renderDiff } from 'diff2html'
// Type-only: the ColorSchemeType enum isn't on diff2html's main export, but
// its values are the plain strings 'dark' | 'light', so we cast to it.
import type { ColorSchemeType } from 'diff2html/lib/types'
import 'diff2html/bundles/css/diff2html.min.css'

// The code deliverable is a raw unified `git diff`. Markdown mangles it, so
// this view is the sanctioned exception to the markdown rule: diff2html gives
// a real diff renderer (line-by-line, +/- gutters, syntax of changes). Its
// palette is diff2html's own — we only steer light/dark from the Vuetify
// theme and blend the container into the surrounding surface.
const props = defineProps<{ diff: string }>()

const theme = useTheme()

const rendered = computed(() =>
  renderDiff(props.diff, {
    drawFileList: false,
    matching: 'lines',
    outputFormat: 'line-by-line',
    colorScheme: (theme.global.current.value.dark
      ? 'dark'
      : 'light') as ColorSchemeType,
  }),
)
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- diff2html output is derived
       from our own git diff, not user-authored HTML -->
  <div class="diff-view" v-html="rendered" />
</template>

<!-- Not scoped: diff2html emits global `.d2h-*` markup into v-html, which a
     scoped selector cannot reach. Everything is nested under `.diff-view` so
     the overrides stay contained to this component. -->
<style>
.diff-view .d2h-wrapper {
  border-radius: 8px;
  overflow: hidden;
}
.diff-view .d2h-file-wrapper {
  border-radius: 8px;
  margin-bottom: 0;
}
.diff-view .d2h-code-line,
.diff-view .d2h-code-linenumber,
.diff-view td {
  font-size: 0.8125rem;
}
</style>

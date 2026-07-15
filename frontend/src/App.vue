<script setup lang="ts">
import { computed, ref } from 'vue'
import { useTheme } from 'vuetify'
import SessionPanel from './components/SessionPanel.vue'
import WorkflowPanel from './components/WorkflowPanel.vue'
import NotificationCenter from './components/NotificationCenter.vue'
import GithubLink from './components/GithubLink.vue'
import { useSessions } from './composables/useSessions'
import { useWorkflows } from './composables/useWorkflows'

// Shared composable state: the header reflects fleet-wide status.
const { sessions, loading: sessionsLoading } = useSessions()
const { loading: workflowsLoading } = useWorkflows()
const running = computed(() =>
  sessions.value.some((s) => s.status === 'running'),
)

// Page-level loading: a thin indeterminate bar under the app bar while any
// primary fetch (sessions or workflows) is in flight (module-vue-vuetify
// loading-feedback rule).
const loading = computed(() => sessionsLoading.value || workflowsLoading.value)

// Workflows lead; the raw sessions view is kept only as a debugging
// affordance (the muted toggle in the header).
const view = ref<'sessions' | 'workflows'>('workflows')

// Light/dark toggle over Vuetify's two built-in themes.
const theme = useTheme()
const isDark = computed(() => theme.current.value.dark)
function toggleTheme() {
  theme.change(isDark.value ? 'light' : 'dark')
}
</script>

<template>
  <v-app>
    <v-app-bar flat border>
      <template #prepend>
        <img src="/logo.svg" alt="kestrel logo" height="32" class="ms-2" />
      </template>
      <v-app-bar-title>
        kestrel
        <span class="text-medium-emphasis text-caption ms-2"
          >mission control</span
        >
      </v-app-bar-title>

      <v-btn-toggle
        v-model="view"
        mandatory
        variant="outlined"
        divided
        density="comfortable"
        class="me-4"
      >
        <v-btn value="workflows" size="small" class="text-none"
          >Workflows</v-btn
        >
        <v-btn
          value="sessions"
          size="small"
          class="text-none"
          title="Raw agent sessions (debugging)"
        >
          <span aria-hidden="true">‹/›</span>&nbsp;sessions
        </v-btn>
      </v-btn-toggle>

      <v-chip
        :color="running ? 'success' : undefined"
        variant="tonal"
        label
        class="me-2"
      >
        <v-icon
          :icon="running ? 'mdi-circle' : 'mdi-circle-outline'"
          size="x-small"
          start
        />
        {{ running ? 'live' : 'idle' }}
      </v-chip>

      <NotificationCenter @navigate="view = 'workflows'" />
      <v-btn
        :icon="isDark ? 'mdi-weather-night' : 'mdi-weather-sunny'"
        variant="text"
        :title="isDark ? 'Switch to light theme' : 'Switch to dark theme'"
        @click="toggleTheme"
      />
      <GithubLink />

      <v-progress-linear
        v-if="loading"
        absolute
        color="primary"
        indeterminate
        location="bottom"
      />
    </v-app-bar>

    <v-main class="stageroot">
      <SessionPanel v-if="view === 'sessions'" />
      <WorkflowPanel v-else />
    </v-main>
  </v-app>
</template>

<style scoped>
/* Let the two-pane consoles own the full height below the app bar; their
   inner scroll regions handle overflow. v-main is border-box with a
   padding-top equal to the app-bar height, so its content box is the
   remaining viewport height. */
.stageroot {
  height: 100dvh;
}
</style>

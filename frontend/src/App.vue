<script setup lang="ts">
import { computed } from 'vue'
import { useTheme } from 'vuetify'
import { useRouter } from 'vue-router'
import NotificationCenter from './components/NotificationCenter.vue'
import SourceHealthIndicator from './components/SourceHealthIndicator.vue'
import GithubLink from './components/GithubLink.vue'
import IdentityBadge from './components/IdentityBadge.vue'
import { useSessions } from './composables/useSessions'
import { useBoard } from './composables/useBoard'
import { useConnectivity } from './composables/useConnectivity'

const router = useRouter()

// Shared composable state: the header's loading bar covers every
// primary fetch. (A fleet-wide live/idle chip was removed: it reflected
// ad-hoc sessions only, and read "idle" while board requests worked —
// each request's own activity line says that now, feature 033.)
const { loading: sessionsLoading } = useSessions()
const { loading: boardLoading } = useBoard()

// Registered once, here, before any child's onMounted fetch runs — every
// api.* call anywhere in the app feeds this, so a request that can't even
// reach the backend (wrong port, backend down) surfaces as a persistent
// banner instead of failing silently in the console.
const { reachable, apiBase } = useConnectivity()

// Page-level loading: a thin indeterminate bar under the app bar while any
// primary fetch (sessions or board) is in flight (module-vue-vuetify
// loading-feedback rule).
const loading = computed(() => sessionsLoading.value || boardLoading.value)

// A notification's request opens directly on that request's cockpit
// (FR-028), not just the board (feature 029, replacing the old
// `view = 'board'` toggle-flip).
function onNotificationNavigate(workflowId: string): void {
  void router.push({ name: 'cockpit', params: { id: workflowId } })
}

// Light/dark toggle over Vuetify's two built-in themes.
const theme = useTheme()
const isDark = computed(() => theme.current.value.dark)
function toggleTheme() {
  theme.change(isDark.value ? 'light' : 'dark')
}
</script>

<template>
  <v-app>
    <v-alert
      v-if="!reachable"
      type="error"
      variant="flat"
      density="compact"
      tile
      class="connectivity-banner"
    >
      Cannot reach the kestrel backend at <code>{{ apiBase }}</code
      >. Check that it's running and that the frontend's configured API base
      matches its port — this clears automatically once it's reachable again.
    </v-alert>

    <v-app-bar flat border>
      <template #prepend>
        <!-- Theme-matched mark: the dark-outlined logo reads on the light
             theme, the plain-fill logo reads on the dark theme. It links
             home, to the board. -->
        <router-link
          :to="{ name: 'board' }"
          aria-label="kestrel home"
          class="d-flex ms-2"
        >
          <img
            :src="isDark ? '/logo-dark.svg' : '/logo-bright.svg'"
            alt="kestrel logo"
            height="32"
          />
        </router-link>
      </template>
      <v-app-bar-title> kestrel </v-app-bar-title>

      <v-btn :to="{ name: 'board' }" size="small" class="text-none me-1">
        Board
      </v-btn>
      <v-btn
        :to="{ name: 'sessions' }"
        size="small"
        class="text-none me-4"
        title="Raw agent sessions (debugging)"
      >
        <span aria-hidden="true">‹/›</span>&nbsp;sessions
      </v-btn>

      <SourceHealthIndicator />
      <NotificationCenter @navigate="onNotificationNavigate" />
      <v-btn
        :icon="isDark ? '$weatherNight' : '$weatherSunny'"
        variant="text"
        :title="isDark ? 'Switch to light theme' : 'Switch to dark theme'"
        @click="toggleTheme"
      />
      <IdentityBadge />
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
      <RouterView />
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

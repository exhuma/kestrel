import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import 'vuetify/styles'
import { aliases as vuetifyAliases, mdi } from 'vuetify/iconsets/mdi-svg'
import { setAuthSuccessHandler, setUnauthorizedHandler } from './api'
import { isAuthCallbackPath, resolveReturnTo } from './auth/callback'
import { initAuth } from './auth/oidc'
import { handleUnauthorized, notifyAuthSuccess } from './auth/reauthGuard'
import { aliases as appAliases } from './plugins/icons'
import './styles/theme.css'
import App from './App.vue'
import { applyDeepLink } from './lib/deeplink'
import { useWorkflows } from './composables/useWorkflows'

// Vuetify's built-in `light` and `dark` themes carry the whole palette — the
// app no longer ships a bespoke colour system. Components auto-import on demand
// via vite-plugin-vuetify (see vite.config.ts), so the bundle only carries what
// is used. Global `defaults` set the house style once (density, variants) so
// individual call sites stay prop-light.
const vuetify = createVuetify({
  // SVG icon set (@mdi/js paths) instead of the webfont: only the referenced
  // glyphs ship. Merge Vuetify's own mdi-svg aliases (used by built-in
  // component icons like $dropdown/$close) with the app's registry.
  icons: {
    defaultSet: 'mdi',
    aliases: { ...vuetifyAliases, ...appAliases },
    sets: { mdi },
  },
  theme: {
    defaultTheme: 'dark',
  },
  defaults: {
    global: { density: 'comfortable' },
    VBtn: { variant: 'flat', rounded: 'lg' },
    VTextField: {
      variant: 'outlined',
      density: 'compact',
      hideDetails: 'auto',
    },
    VTextarea: {
      variant: 'outlined',
      density: 'compact',
      autoGrow: true,
      hideDetails: 'auto',
    },
    VSelect: { variant: 'outlined', density: 'compact', hideDetails: 'auto' },
    VList: { density: 'compact' },
    VChip: { size: 'small' },
    VAlert: { variant: 'tonal', density: 'compact' },
  },
})

function mount(): void {
  // Deep-link: if the URL carries `?run=<id>` (from a gate-notification
  // comment), open that run before mount so the panel shows its gate form.
  applyDeepLink(window.location.search, (id) => useWorkflows().select(id))
  createApp(App).use(vuetify).mount('#app')
}

/**
 * Resolve auth state and, when enabled, gate mounting behind sign-in.
 *
 * No vue-router: the `/auth/callback` redirect target is handled manually
 * here (mirroring the existing `applyDeepLink` manual-URL-parsing idiom
 * above), and "requires sign-in" is enforced by not mounting `App` at all
 * until a valid, non-expired user is present — appropriate for an app with
 * exactly one meaningful page rather than per-route guards.
 */
async function bootstrap(): Promise<void> {
  const auth = await initAuth()
  if (!auth.enabled || !auth.userManager) {
    mount()
    return
  }
  const userManager = auth.userManager

  setUnauthorizedHandler(() =>
    handleUnauthorized(() =>
      void userManager.signinRedirect({ state: window.location.pathname }),
    ),
  )
  setAuthSuccessHandler(notifyAuthSuccess)

  if (isAuthCallbackPath(window.location.pathname)) {
    const user = await userManager.signinRedirectCallback()
    window.history.replaceState({}, '', resolveReturnTo(user.state))
    mount()
    return
  }

  const user = await userManager.getUser()
  if (!user || user.expired) {
    await userManager.signinRedirect({ state: window.location.pathname })
    return // navigating away to the IdP; do not mount
  }
  mount()
}

void bootstrap()

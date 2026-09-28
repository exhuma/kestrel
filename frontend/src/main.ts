import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import 'vuetify/styles'
import { aliases as vuetifyAliases, mdi } from 'vuetify/iconsets/mdi-svg'
import { aliases as appAliases } from './plugins/icons'
import './styles/theme.css'
import App from './App.vue'
import { router } from './router'
import { applyDeepLink } from './lib/deeplink'

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

// Legacy deep-link (FR-031): `?run=<id>` (from a gate-notification
// comment) resolves to the request's cockpit, but only when no hash
// route is already present — a bookmarked `#/requests/:id` must not be
// overridden by a stale `?run=` query string still hanging on the URL.
const hasHashRoute =
  window.location.hash !== '' && window.location.hash !== '#/'
if (!hasHashRoute) {
  applyDeepLink(
    window.location.search,
    (id) => void router.replace({ name: 'cockpit', params: { id } }),
  )
}

createApp(App).use(vuetify).use(router).mount('#app')

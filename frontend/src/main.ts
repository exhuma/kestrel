import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import 'vuetify/styles'
import { aliases as vuetifyAliases, mdi } from 'vuetify/iconsets/mdi-svg'
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

// Deep-link: if the URL carries `?run=<id>` (from a gate-notification
// comment), open that run before mount so the panel shows its gate form.
applyDeepLink(window.location.search, (id) => useWorkflows().select(id))

createApp(App).use(vuetify).mount('#app')

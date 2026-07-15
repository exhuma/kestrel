import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'
import './styles/theme.css'
import App from './App.vue'

// Vuetify's built-in `light` and `dark` themes carry the whole palette — the
// app no longer ships a bespoke colour system. Components auto-import on demand
// via vite-plugin-vuetify (see vite.config.ts), so the bundle only carries what
// is used. Global `defaults` set the house style once (density, variants) so
// individual call sites stay prop-light.
const vuetify = createVuetify({
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

createApp(App).use(vuetify).mount('#app')

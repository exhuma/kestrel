import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import 'vuetify/styles'
import { missionControlDark, missionControlLight } from './theme'
import './styles/theme.css'
import App from './App.vue'

// Components and directives are auto-imported on demand by vite-plugin-vuetify
// (see vite.config.ts), so the bundle only carries the Vuetify pieces actually
// used. The theme is single-sourced from ./theme.
const vuetify = createVuetify({
  theme: {
    defaultTheme: 'missionControl',
    themes: {
      missionControl: missionControlDark,
      missionControlLight,
    },
  },
})

createApp(App).use(vuetify).mount('#app')

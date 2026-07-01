import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import 'vuetify/styles'
import './styles/theme.css'
import App from './App.vue'

// Vuetify theme mirrors the Mission Control tokens in styles/theme.css
// so any Vuetify component picks up the same palette.
const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'missionControl',
    themes: {
      missionControl: {
        dark: true,
        colors: {
          background: '#0B1220',
          surface: '#16213A',
          primary: '#35E6C9',
          secondary: '#6EA8FF',
          error: '#F2727F',
          info: '#6EA8FF',
          success: '#5BD98A',
          warning: '#F5B14C',
        },
      },
    },
  },
})

createApp(App).use(vuetify).mount('#app')

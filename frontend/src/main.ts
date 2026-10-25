import { createApp } from 'vue'
import 'vuetify/styles'
import { createAppVuetify } from './plugins/vuetify'
import './styles/theme.css'
import App from './App.vue'
import { router } from './router'

const vuetify = createAppVuetify()

createApp(App).use(vuetify).use(router).mount('#app')

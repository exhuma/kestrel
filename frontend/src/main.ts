import { createApp } from 'vue'
import 'vuetify/styles'
import { createAppVuetify } from './plugins/vuetify'
import './styles/theme.css'
import App from './App.vue'
import { router } from './router'
import { applyDeepLink } from './lib/deeplink'

const vuetify = createAppVuetify()

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

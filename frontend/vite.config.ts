import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'

// https://vite.dev/config/
export default defineConfig({
  // vite-plugin-vuetify auto-imports Vuetify components/directives on use and
  // tree-shakes the rest, so we neither register them globally nor ship the
  // whole library.
  plugins: [vue(), vuetify({ autoImport: true })],
  test: {
    environment: 'happy-dom',
    // Register global stubs (ResizeObserver) that Vuetify components need
    // under happy-dom.
    setupFiles: ['./tests/support/setup.ts'],
    // Process Vuetify through Vite in tests so its per-component `.css`
    // imports go through the CSS pipeline instead of Node's ESM loader.
    server: { deps: { inline: ['vuetify'] } },
  },
})

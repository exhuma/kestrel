// Shared Vuetify instance for component tests. Components migrated to Vuetify
// need the plugin installed on the test app so theme/defaults inject; mount
// them with `mount(Component, withVuetify())`. Components themselves are
// auto-imported by vite-plugin-vuetify (see vite.config.ts), so this instance
// only provides the plugin (theme/defaults), not a component registry.
import { createVuetify } from 'vuetify'
import { themeOptions } from '../../src/plugins/vuetify'

// The app's themes (feature 039: the specialist colours), without its
// defaults, so existing component tests keep Vuetify's own defaults.
export const vuetify = createVuetify({ theme: themeOptions })

export function withVuetify(options: Record<string, unknown> = {}): {
  global: { plugins: unknown[] }
} {
  const globalOpts = (options.global as Record<string, unknown>) ?? {}
  const plugins = (globalOpts.plugins as unknown[]) ?? []
  return {
    ...options,
    global: { ...globalOpts, plugins: [vuetify, ...plugins] },
  }
}

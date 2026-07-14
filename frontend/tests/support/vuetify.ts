// Shared Vuetify instance for component tests. Components migrated to Vuetify
// need the plugin installed on the test app so theme/defaults inject; mount
// them with `mount(Component, withVuetify())`. Components themselves are
// auto-imported by vite-plugin-vuetify (see vite.config.ts), so this instance
// only provides the plugin (theme/defaults), not a component registry.
import { createVuetify } from 'vuetify'

export const vuetify = createVuetify()

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

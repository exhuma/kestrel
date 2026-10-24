// The app's Vuetify configuration, shared by `main.ts` and the component
// tests (`tests/support/vuetify.ts`) so both render the same theme.
//
// Vuetify's built-in `light` and `dark` themes carry the palette; the app
// adds only semantic colours of its own — one per specialist (feature 039,
// `lib/specialistColor.ts`). Components auto-import on demand via
// vite-plugin-vuetify (see vite.config.ts). Global `defaults` set the house
// style once (density, variants) so individual call sites stay prop-light.
import { createVuetify, type ThemeDefinition } from 'vuetify'
import { aliases as vuetifyAliases, mdi } from 'vuetify/iconsets/mdi-svg'
import { aliases as appAliases } from './icons'
import { specialistThemeColors } from '../lib/specialistColor'

/** The themes: Vuetify's own, plus the specialist colours. */
export const themeOptions: {
  defaultTheme: string
  themes: Record<string, ThemeDefinition>
} = {
  defaultTheme: 'dark',
  themes: {
    light: { colors: specialistThemeColors('light') },
    dark: { colors: specialistThemeColors('dark') },
  },
}

export function createAppVuetify() {
  return createVuetify({
    // SVG icon set (@mdi/js paths) instead of the webfont: only the
    // referenced glyphs ship. Merge Vuetify's own mdi-svg aliases (used by
    // built-in component icons like $dropdown/$close) with the app's.
    icons: {
      defaultSet: 'mdi',
      aliases: { ...vuetifyAliases, ...appAliases },
      sets: { mdi },
    },
    theme: themeOptions,
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
}

// Single source for the "Mission Control" palette.
//
// The Vuetify theme (see main.ts) is built from `palette` below, so adopted
// Vuetify components draw their colours from the same values the hand-rolled
// CSS in styles/theme.css uses. Collapsing styles/theme.css to *also* derive
// from this module (removing the parallel `--ink-*` custom properties) is the
// WP6 design-token follow-up; this WP makes this module the authoritative
// colour source that WP6 will fan out.
import type { ThemeDefinition } from 'vuetify'

/** Raw brand colours, defined once. */
export const palette = {
  ink900: '#0b1220', // app background — deepest
  ink850: '#0e1626', // header / recessed
  ink800: '#111a2b', // dispatch rail
  ink750: '#14203a', // input wells
  ink700: '#16213a', // cards / stage surface
  ink650: '#1b2942', // hover
  line: '#223049', // hairline borders
  textHi: '#e6edf7',
  textMid: '#9fb0c7',
  textDim: '#62748c',
  signal: '#35e6c9', // primary action / live
  signalInk: '#04231f', // text on signal fills
  user: '#6ea8ff', // secondary / info
  ok: '#5bd98a', // success
  warn: '#f5b14c', // warning
  err: '#f2727f', // error
} as const

/**
 * The default dark theme — the current Mission Control look. Vuetify computes
 * legible `on-*` foregrounds automatically; `on-primary` is pinned to the
 * dark signal-ink so text on the teal primary stays readable.
 */
export const missionControlDark: ThemeDefinition = {
  dark: true,
  colors: {
    background: palette.ink900,
    surface: palette.ink700,
    'surface-bright': palette.ink650,
    'surface-light': palette.ink750,
    primary: palette.signal,
    'on-primary': palette.signalInk,
    secondary: palette.user,
    info: palette.user,
    success: palette.ok,
    warning: palette.warn,
    error: palette.err,
    'on-surface': palette.textHi,
  },
  variables: {
    'border-color': palette.line,
    'theme-on-surface-variant': palette.textMid,
  },
}

/**
 * A light counterpart, provided so the theme is not dark-only (module-vue-
 * vuetify expects both). The app currently defaults to and only exercises the
 * dark theme; this exists for a future in-app theme switch.
 */
export const missionControlLight: ThemeDefinition = {
  dark: false,
  colors: {
    background: '#f4f7fb',
    surface: '#ffffff',
    'surface-bright': '#ffffff',
    'surface-light': '#eef2f8',
    primary: '#0f9e8a',
    'on-primary': '#ffffff',
    secondary: '#2f6ad0',
    info: '#2f6ad0',
    success: '#1f9d57',
    warning: '#b9761d',
    error: '#c8414c',
    'on-surface': '#12202f',
  },
  variables: {
    'border-color': '#d4deea',
    'theme-on-surface-variant': '#4a5c70',
  },
}

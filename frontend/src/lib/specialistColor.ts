/**
 * One colour per kestrel specialist (feature 039), so each specialist's
 * part of the page — its interview questions above all — reads as its
 * own. Registered as Vuetify theme colours `specialist-<id>` in both
 * themes (`plugins/vuetify.ts`); components use the theme name, never
 * a literal.
 *
 * Light values are dark enough to read on white, dark values light
 * enough to read on the dark surface. Colour is never the only signal:
 * whatever is coloured also names its specialist.
 */

export interface SpecialistShade {
  light: string
  dark: string
}

/** The built-in roster (`backend/app/services/board/specialists.py`
 *  `DEFAULT_ROLE_IDS`). An operator-added specialist has no colour and
 *  is shown neutrally. */
export const SPECIALIST_PALETTE: Readonly<Record<string, SpecialistShade>> = {
  requester: { light: '#B45309', dark: '#FCD34D' },
  pm: { light: '#1D4ED8', dark: '#93C5FD' },
  uiux: { light: '#BE185D', dark: '#F9A8D4' },
  developer: { light: '#047857', dark: '#6EE7B7' },
  infosec: { light: '#B91C1C', dark: '#FCA5A5' },
  dba: { light: '#6D28D9', dark: '#C4B5FD' },
  architect: { light: '#0E7490', dark: '#67E8F9' },
  ops: { light: '#4D7C0F', dark: '#BEF264' },
  qa: { light: '#C2410C', dark: '#FDBA74' },
  coordinator: { light: '#334155', dark: '#CBD5E1' },
  coder: { light: '#0F766E', dark: '#5EEAD4' },
  verifier: { light: '#4338CA', dark: '#A5B4FC' },
  'input-security': { light: '#A16207', dark: '#FDE047' },
}

/** The theme colour name for *specialistId*, or `null` for a specialist
 *  outside the palette. */
export function specialistColor(specialistId: string): string | null {
  return specialistId in SPECIALIST_PALETTE
    ? `specialist-${specialistId}`
    : null
}

/** Theme `colors` entries for one theme (`light` or `dark`). */
export function specialistThemeColors(
  theme: keyof SpecialistShade,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(SPECIALIST_PALETTE).map(([id, shade]) => [
      `specialist-${id}`,
      shade[theme],
    ]),
  )
}

import { describe, expect, it } from 'vitest'
import {
  SPECIALIST_PALETTE,
  specialistColor,
  specialistThemeColors,
} from '../../src/lib/specialistColor'

describe('specialistColor (feature 039)', () => {
  it('names the theme colour of a built-in specialist', () => {
    expect(specialistColor('uiux')).toBe('specialist-uiux')
    expect(specialistColor('input-security')).toBe('specialist-input-security')
  })

  it('leaves an operator-added specialist neutral', () => {
    expect(specialistColor('lawyer')).toBeNull()
  })

  it('gives every specialist its own colour, in each theme', () => {
    for (const theme of ['light', 'dark'] as const) {
      const colors = Object.values(specialistThemeColors(theme))
      expect(new Set(colors).size).toBe(Object.keys(SPECIALIST_PALETTE).length)
    }
  })
})

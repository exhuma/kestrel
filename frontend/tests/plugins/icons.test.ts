import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { aliases as appAliases } from '../../src/plugins/icons'
import { aliases as vuetifyAliases } from 'vuetify/iconsets/mdi-svg'

// vitest runs with the frontend package root as cwd.
const srcDir = join(process.cwd(), 'src')

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) return walk(full)
    return entry.name.endsWith('.vue') || entry.name.endsWith('.ts')
      ? [full]
      : []
  })
}

const sources = walk(srcDir).map((path) => ({
  path,
  text: readFileSync(path, 'utf8'),
}))

// Merged set actually installed on the Vuetify instance (main.ts). A referenced
// `$alias` must resolve here or the UI shows a missing-glyph placeholder.
const resolvable = { ...vuetifyAliases, ...appAliases }

// The glyphs the UI is expected to carry. Kept at module level rather than
// inline so adding an icon does not push the describe block past the
// function-length limit.
const EXPECTED_ALIASES = [
  'account',
  'accountClock',
  'alertCircle',
  'arrowRight',
  'bell',
  'broom',
  'checkCircle',
  'circle',
  'circleOutline',
  'close',
  'codeJson',
  'cogOutline',
  'fileDocumentOutline',
  'forumOutline',
  'gavel',
  'helpCircleOutline',
  'inboxArrowDown',
  'minusCircleOutline',
  'progressClock',
  'radar',
  'refresh',
  'restart',
  'rocketLaunchOutline',
  'shieldAlert',
  'sitemapOutline',
  'sourcePull',
  'subdirectoryArrowRight',
  'textBoxCheckOutline',
  'weatherNight',
  'weatherSunny',
]

describe('icon alias registry', () => {
  it('maps every app alias to a non-empty SVG path', () => {
    for (const [name, path] of Object.entries(appAliases)) {
      expect(path, `alias $${name} has an empty path`).toBeTruthy()
      expect(typeof path).toBe('string')
    }
  })

  it('registers exactly the glyphs the UI references', () => {
    expect(Object.keys(appAliases).sort()).toEqual(EXPECTED_ALIASES.sort())
  })
})

describe('icon references in src/', () => {
  it('has no leftover mdi-* webfont icon names in src/', () => {
    const offenders = sources
      .filter(({ text }) => /["']mdi-[a-z-]+["']/.test(text))
      .map(({ path }) => path)
    expect(
      offenders,
      `mdi-* webfont refs remain in: ${offenders.join(', ')}`,
    ).toHaveLength(0)
  })

  it('resolves every $alias icon referenced in templates', () => {
    const missing: string[] = []
    for (const { path, text } of sources) {
      for (const match of text.matchAll(/["']\$([A-Za-z][A-Za-z0-9]*)["']/g)) {
        const name = match[1]
        if (!(name in resolvable)) missing.push(`$${name} (${path})`)
      }
    }
    expect(
      missing,
      `unresolved icon aliases: ${missing.join(', ')}`,
    ).toHaveLength(0)
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'

// `API_BASE` is resolved once at module load from `import.meta.env`, so each
// case stubs the env and re-imports the module. This documents the three-way
// contract the zero-config dev default depends on:
//   - unset          -> in-code default http://localhost:8000 (run-from-source)
//   - empty string   -> '' same-origin (packaged image serves the bundle)
//   - explicit value -> used verbatim (developer override wins)
async function loadApiBase(): Promise<string> {
  vi.resetModules()
  const mod = await import('../../src/api')
  return mod.API_BASE
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('API_BASE default resolution', () => {
  it('falls back to http://localhost:8000 when VITE_API_BASE is unset', async () => {
    vi.stubEnv('VITE_API_BASE', undefined as unknown as string)
    expect(await loadApiBase()).toBe('http://localhost:8000')
  })

  it('is same-origin (empty string) when VITE_API_BASE is empty', async () => {
    vi.stubEnv('VITE_API_BASE', '')
    expect(await loadApiBase()).toBe('')
  })

  it('uses an explicit VITE_API_BASE value verbatim', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://localhost:9999')
    expect(await loadApiBase()).toBe('http://localhost:9999')
  })
})

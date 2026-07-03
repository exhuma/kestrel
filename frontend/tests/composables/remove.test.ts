import { describe, it, expect, vi, afterEach } from 'vitest'
import { useSessions } from '../../src/composables/useSessions'
import { useWorkflows } from '../../src/composables/useWorkflows'

afterEach(() => {
  vi.restoreAllMocks()
})

interface Call {
  url: string
  method: string
}

function stubFetch(listPath: string): Call[] {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), method: init?.method ?? 'GET' })
      const body = String(input).endsWith(listPath) ? [] : { status: 'ok' }
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
  return calls
}

describe('abandon (delete) wiring', () => {
  it('useSessions.remove issues DELETE then refreshes the list', async () => {
    const calls = stubFetch('/api/sessions')
    await useSessions().remove('s1')
    expect(
      calls.some(
        (c) => c.method === 'DELETE' && c.url.includes('/api/sessions/s1'),
      ),
    ).toBe(true)
    expect(
      calls.some((c) => c.method === 'GET' && c.url.endsWith('/api/sessions')),
    ).toBe(true)
  })

  it('useWorkflows.remove issues DELETE then refreshes the list', async () => {
    const calls = stubFetch('/api/workflows')
    await useWorkflows().remove('wf-1')
    expect(
      calls.some(
        (c) => c.method === 'DELETE' && c.url.includes('/api/workflows/wf-1'),
      ),
    ).toBe(true)
    expect(
      calls.some(
        (c) => c.method === 'GET' && c.url.endsWith('/api/workflows'),
      ),
    ).toBe(true)
  })
})

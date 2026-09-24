import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useBoard } from '../../src/composables/useBoard'
import type { BoardSnapshot, WorkCardSummary } from '../../src/types/workflows'

let esInstances = 0
let lastEs: FakeEventSource | null = null
class FakeEventSource {
  onmessage: ((e: MessageEvent) => void) | null = null
  close = vi.fn()
  constructor(public url: string) {
    esInstances += 1
    lastEs = this
  }
  emit(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent)
  }
}

beforeEach(() => {
  esInstances = 0
  lastEs = null
  vi.stubGlobal('EventSource', FakeEventSource)
  useBoard().stop()
  useBoard().current.value = null
})
afterEach(() => {
  useBoard().stop()
  vi.restoreAllMocks()
})

function snapshot(id: string, overrides: Partial<BoardSnapshot> = {}): BoardSnapshot {
  return {
    id,
    revision: 1,
    task_label: 'o/r#1',
    status: 'active',
    cards: [],
    relationships: [],
    state_counts: {},
    ...overrides,
  }
}

function card(overrides: Partial<WorkCardSummary> = {}): WorkCardSummary {
  return {
    id: 'card-1',
    title: 'Investigate',
    card_type: 'analysis',
    state: 'ready',
    eligible_roles: [],
    owner: null,
    lease: null,
    waiting_reason: null,
    dependency_count: 0,
    latest_artifact: null,
    allowed_actions: [],
    ...overrides,
  }
}

describe('useBoard refresh', () => {
  it('populates workflows from the api', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify([
              {
                id: 'wf-1',
                task_label: 'o/r#1',
                status: 'active',
                state_counts: {},
                action_required_count: 0,
              },
            ]),
            { status: 200 },
          ),
      ),
    )
    const { workflows, refresh } = useBoard()
    await refresh()
    expect(workflows.value.map((w) => w.id)).toContain('wf-1')
  })

  it('surfaces a request failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('unavailable', { status: 503 })),
    )
    const { error, refresh } = useBoard()

    await refresh()

    expect(error.value).toBe('Request failed (503)')
  })
})

describe('useBoard select', () => {
  it('opens a board event stream and applies snapshots', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () => new Response(JSON.stringify(snapshot('wf-1')), { status: 200 }),
      ),
    )
    const { select, current } = useBoard()
    await select('wf-1')
    expect(esInstances).toBe(1)
    expect(lastEs?.url).toContain('/api/board/workflows/wf-1/board/events')
    lastEs?.emit(snapshot('wf-1', { revision: 2 }))
    expect(current.value?.revision).toBe(2)
  })

  it('ignores a snapshot for a workflow no longer selected', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const id = url.includes('wf-2') ? 'wf-2' : 'wf-1'
        return new Response(JSON.stringify(snapshot(id)), { status: 200 })
      }),
    )
    const { select, current } = useBoard()
    await select('wf-1')
    const stale = lastEs
    await select('wf-2')
    stale?.emit(snapshot('wf-1', { revision: 99 }))
    expect(current.value?.id).toBe('wf-2')
  })

  it('stop closes the detail stream', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () => new Response(JSON.stringify(snapshot('wf-1')), { status: 200 }),
      ),
    )
    const { select, stop } = useBoard()
    await select('wf-1')
    stop()
    expect(lastEs?.close).toHaveBeenCalled()
  })
})

describe('useBoard applyIntervention', () => {
  it('posts with the current revision', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === 'POST') {
          return new Response(JSON.stringify(card({ state: 'cancelled' })), {
            status: 200,
          })
        }
        return new Response(JSON.stringify(snapshot('wf-1', { revision: 7 })), {
          status: 200,
        })
      }),
    )
    const { select, applyIntervention } = useBoard()
    await select('wf-1')

    const result = await applyIntervention('card-1', 'cancel')

    expect(result?.state).toBe('cancelled')
    const fetchMock = vi.mocked(fetch)
    const lastCall = fetchMock.mock.calls.at(-1)
    const body = JSON.parse((lastCall?.[1]?.body as string) ?? '{}')
    expect(body).toEqual({
      action: 'cancel',
      expected_revision: 7,
      decision: null,
    })
  })

  it('surfaces a stale-revision conflict', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === 'POST') {
          return new Response('stale', { status: 409 })
        }
        return new Response(JSON.stringify(snapshot('wf-1')), { status: 200 })
      }),
    )
    const { select, applyIntervention, error } = useBoard()
    await select('wf-1')

    const result = await applyIntervention('card-1', 'cancel')

    expect(result).toBeNull()
    expect(error.value).toBe('Request failed (409)')
  })

  it('is a no-op without a selected workflow', async () => {
    const { applyIntervention } = useBoard()
    const result = await applyIntervention('card-1', 'cancel')
    expect(result).toBeNull()
  })
})

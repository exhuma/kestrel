import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { useBoardEvents } from '../../src/composables/useBoardEvents'
import { useBoard } from '../../src/composables/useBoard'
import { boardEvent, boardSnapshot } from '../support/board'
import type { BoardEvent } from '../../src/types/workflows'

function stubFetch(pages: BoardEvent[][]): ReturnType<typeof vi.fn> {
  let call = 0
  const fn = vi.fn(async () => {
    const body = pages[Math.min(call, pages.length - 1)]
    call += 1
    return new Response(JSON.stringify(body), { status: 200 })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

/** Publish a snapshot the way the detail SSE does: a whole new object with
 *  a bumped revision. */
async function tick(id: string, revision: number): Promise<void> {
  useBoard().current.value = boardSnapshot({ id, revision })
  await flushPromises()
}

beforeEach(() => {
  useBoardEvents().stop()
  useBoard().current.value = null
})
afterEach(() => {
  useBoardEvents().stop()
  vi.restoreAllMocks()
})

describe('useBoardEvents initial fetch', () => {
  it('fetches the workflow history from its own REST endpoint', async () => {
    const fetchMock = stubFetch([[boardEvent({ payload: 'first' })]])
    const { events, start } = useBoardEvents()
    start('wf-1')
    await flushPromises()
    expect(fetchMock.mock.calls[0][0]).toContain(
      '/api/board/workflows/wf-1/events',
    )
    expect(events.value).toHaveLength(1)
    expect(events.value[0].payload).toBe('first')
  })

  it('reports a failure in words instead of showing an empty history', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('nope', { status: 500 })),
    )
    const { error, start } = useBoardEvents()
    start('wf-1')
    await flushPromises()
    expect(error.value).toContain('500')
  })
})

describe('useBoardEvents live updates', () => {
  it('re-fetches when the snapshot revision ticks', async () => {
    const fetchMock = stubFetch([
      [boardEvent({ payload: 'first' })],
      [boardEvent({ payload: 'first' }), boardEvent({ payload: 'second' })],
    ])
    const { events, start } = useBoardEvents()
    start('wf-1')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await tick('wf-1', 2)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(events.value.map((e) => e.payload)).toEqual(['first', 'second'])
  })

  it('does not duplicate events the endpoint repeats on every re-fetch', async () => {
    const history = [
      boardEvent({ payload: 'first', created_at: '2026-09-28T10:00:00Z' }),
      boardEvent({ payload: 'second', created_at: '2026-09-28T10:01:00Z' }),
    ]
    stubFetch([history, history])
    const { events, start } = useBoardEvents()
    start('wf-1')
    await flushPromises()
    await tick('wf-1', 2)
    expect(events.value).toHaveLength(2)
  })

  it('ignores a snapshot tick belonging to a different workflow', async () => {
    const fetchMock = stubFetch([[boardEvent()]])
    const { start } = useBoardEvents()
    start('wf-1')
    await flushPromises()
    await tick('wf-2', 7)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('useBoardEvents teardown', () => {
  it('clears the history so the next request never shows the previous one', async () => {
    stubFetch([[boardEvent({ payload: 'first' })]])
    const { events, stop, start } = useBoardEvents()
    start('wf-1')
    await flushPromises()
    expect(events.value).toHaveLength(1)
    stop()
    expect(events.value).toEqual([])
  })

  it('stops re-fetching on snapshot ticks once stopped', async () => {
    const fetchMock = stubFetch([[boardEvent()]])
    const { start, stop } = useBoardEvents()
    start('wf-1')
    await flushPromises()
    stop()
    await tick('wf-1', 3)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

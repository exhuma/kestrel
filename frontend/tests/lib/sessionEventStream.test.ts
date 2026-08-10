import { describe, it, expect, vi, afterEach } from 'vitest'
import { openSessionEventStream } from '../../src/lib/sessionEventStream'

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

class FakeEventSource {
  static CLOSED = 2
  onmessage: ((e: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  readyState = 1
  close = vi.fn(() => {
    this.readyState = FakeEventSource.CLOSED
  })

  constructor(public url: string) {
    FakeEventSource.log.push(this)
  }

  emit(data: unknown, lastEventId = ''): void {
    this.onmessage?.({
      data: JSON.stringify(data),
      lastEventId,
    } as MessageEvent)
  }

  fail(): void {
    this.readyState = FakeEventSource.CLOSED
    this.onerror?.()
  }

  static log: FakeEventSource[] = []
}

function lastInstance(): FakeEventSource {
  const i = FakeEventSource.log.at(-1)
  if (!i) throw new Error('no EventSource opened')
  return i
}

describe('openSessionEventStream', () => {
  it('delivers events with increasing ids', () => {
    FakeEventSource.log = []
    vi.stubGlobal('EventSource', FakeEventSource)
    const received: unknown[] = []
    openSessionEventStream('s1', (e) => received.push(e))

    lastInstance().emit({ kind: 'system' }, '1')
    lastInstance().emit({ kind: 'assistant_text' }, '2')

    expect(received).toHaveLength(2)
  })

  it('drops a frame whose id is not newer than the last applied', () => {
    FakeEventSource.log = []
    vi.stubGlobal('EventSource', FakeEventSource)
    const received: unknown[] = []
    openSessionEventStream('s1', (e) => received.push(e))

    lastInstance().emit({ kind: 'system' }, '3')
    lastInstance().emit({ kind: 'stale-replay' }, '2') // <= last seen, dropped
    lastInstance().emit({ kind: 'stale-replay' }, '3') // == last seen, dropped
    lastInstance().emit({ kind: 'assistant_text' }, '4') // newer, delivered

    expect(received).toHaveLength(2)
  })

  it('applies frames with no id (server sent none) unconditionally', () => {
    FakeEventSource.log = []
    vi.stubGlobal('EventSource', FakeEventSource)
    const received: unknown[] = []
    openSessionEventStream('s1', (e) => received.push(e))

    lastInstance().emit({ kind: 'a' })
    lastInstance().emit({ kind: 'b' })

    expect(received).toHaveLength(2)
  })

  it('reopens after the connection is fully closed, reusing lastSeenId', () => {
    vi.useFakeTimers()
    FakeEventSource.log = []
    vi.stubGlobal('EventSource', FakeEventSource)
    const received: unknown[] = []
    openSessionEventStream('s1', (e) => received.push(e))

    lastInstance().emit({ kind: 'system' }, '5')
    lastInstance().fail()
    vi.advanceTimersByTime(3000)

    expect(FakeEventSource.log).toHaveLength(2) // reopened

    // A full replay from the fresh connection is still de-duped against
    // the id seen before the drop.
    lastInstance().emit({ kind: 'stale-replay' }, '5')
    lastInstance().emit({ kind: 'fresh' }, '6')

    expect(received).toHaveLength(2)
  })

  it('close() stops delivering events and does not reconnect', () => {
    vi.useFakeTimers()
    FakeEventSource.log = []
    vi.stubGlobal('EventSource', FakeEventSource)
    const received: unknown[] = []
    const handle = openSessionEventStream('s1', (e) => received.push(e))

    handle.close()
    lastInstance().fail()
    vi.advanceTimersByTime(5000)

    expect(FakeEventSource.log).toHaveLength(1) // no reconnect after close()
  })
})

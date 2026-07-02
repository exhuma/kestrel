import { describe, it, expect, vi, afterEach } from 'vitest'
import { useWorkflows } from '../../src/composables/useWorkflows'

afterEach(() => vi.restoreAllMocks())

describe('useWorkflows', () => {
  it('refresh populates workflows from the api', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify([
            { id: 'wf-1', repo: 'o/r', issue_number: 3, status: 'planning' },
          ]),
          { status: 200 },
        ),
      ),
    )
    const { workflows, refresh } = useWorkflows()
    await refresh()
    expect(workflows.value.map((w) => w.id)).toContain('wf-1')
  })

  it('createWorkflow posts repo and issue number', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ workflow_id: 'wf-9' }), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const { createWorkflow } = useWorkflows()
    const id = await createWorkflow('o/r', 5)
    expect(id).toBe('wf-9')
    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      repo: 'o/r',
      issue_number: 5,
    })
  })

  it('stop closes the active EventSource and clears the poll interval', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            id: 'wf-1',
            repo: 'o/r',
            issue_number: 3,
            issue_title: 't',
            status: 'planning',
            branch: 'b',
            steps: [],
            current_session_id: 'sess-1',
            pr_url: null,
            error: null,
          }),
          { status: 200 },
        ),
      ),
    )
    const closeSpy = vi.fn()
    let instances = 0
    class FakeEventSource {
      onmessage: ((e: MessageEvent) => void) | null = null
      close = closeSpy
      constructor(public url: string) {
        instances += 1
      }
    }
    vi.stubGlobal('EventSource', FakeEventSource)

    const { select, stop } = useWorkflows()
    select('wf-1')
    // allow the initial loadDetail() call to resolve and open the EventSource
    await vi.waitFor(() => expect(instances).toBeGreaterThan(0))

    stop()

    expect(closeSpy).toHaveBeenCalled()
  })

  it('ensureLive resumes detail polling after stop', async () => {
    // Regression: switching views unmounts the panel (stop());
    // remounting must resume polling for the selected run, or the
    // UI freezes and never shows the awaiting_input reply gate.
    vi.useFakeTimers()
    try {
      class FakeEventSource {
        onmessage: ((e: MessageEvent) => void) | null = null
        close(): void {}
        constructor(public url: string) {}
      }
      vi.stubGlobal('EventSource', FakeEventSource)
      const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
        String(input).endsWith('/api/workflows')
          ? new Response(JSON.stringify([]), { status: 200 })
          : new Response(
              JSON.stringify({
                id: 'wf-1',
                repo: 'o/r',
                issue_number: 3,
                issue_title: 't',
                status: 'refining',
                branch: 'b',
                steps: [],
                current_session_id: 'sess-1',
                pr_url: null,
                error: null,
              }),
              { status: 200 },
            ),
      )
      vi.stubGlobal('fetch', fetchMock)

      const { select, stop, ensureLive } = useWorkflows()
      select('wf-1')
      await vi.advanceTimersByTimeAsync(3200)
      const whilePolling = fetchMock.mock.calls.length
      expect(whilePolling).toBeGreaterThan(1)

      stop() // what onUnmounted does when the user switches views
      await vi.advanceTimersByTimeAsync(5000)
      const afterStop = fetchMock.mock.calls.length
      expect(afterStop).toBe(whilePolling)

      ensureLive() // what onMounted must do when the user returns
      await vi.advanceTimersByTimeAsync(3200)
      expect(fetchMock.mock.calls.length).toBeGreaterThan(afterStop)
      stop()
    } finally {
      vi.useRealTimers()
    }
  })
})

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
})

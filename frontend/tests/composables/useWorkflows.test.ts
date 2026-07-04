import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useWorkflows } from '../../src/composables/useWorkflows'

// A minimal EventSource stand-in: records how many streams opened, the
// last url, and lets a test push a message frame.
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
})
afterEach(() => {
  useWorkflows().stop()
  vi.restoreAllMocks()
})

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
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith('/api/workflows')
        ? new Response(JSON.stringify({ workflow_id: 'wf-9' }), { status: 200 })
        : new Response(JSON.stringify([]), { status: 200 }),
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

  it('select opens a workflow event stream and applies snapshots', async () => {
    const { select, current } = useWorkflows()
    select('wf-1')
    expect(esInstances).toBe(1)
    expect(lastEs?.url).toContain('/api/workflows/wf-1/events')
    lastEs?.emit({
      id: 'wf-1', repo: 'o/r', issue_number: 3, issue_title: 't',
      status: 'refining', branch: 'b', steps: [],
      current_session_id: null, active_sessions: [], pr_url: null,
      error: null,
    })
    expect(current.value?.status).toBe('refining')
  })

  it('applies live snapshots to the sidebar list card status', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify([
            { id: 'wf-2', repo: 'o/r', issue_number: 4, status: 'cloning' },
          ]),
          { status: 200 },
        ),
      ),
    )
    const { workflows, refresh, select } = useWorkflows()
    await refresh()
    select('wf-2')
    lastEs?.emit({
      id: 'wf-2', repo: 'o/r', issue_number: 4, issue_title: 't',
      status: 'refining', branch: 'b', steps: [],
      current_session_id: null, active_sessions: [], pr_url: null,
      error: null,
    })
    // The list card status advanced from its create-time value, live.
    expect(workflows.value.find((w) => w.id === 'wf-2')?.status).toBe('refining')
  })

  it('stop closes the active EventSource', async () => {
    const { select, stop } = useWorkflows()
    select('wf-1')
    const closed = lastEs!.close
    stop()
    expect(closed).toHaveBeenCalled()
  })

  it('ensureLive resumes the stream after stop', async () => {
    // Regression: switching views unmounts the panel (stop());
    // remounting must reopen the stream for the selected run, or the
    // UI freezes and never shows the awaiting_input reply gate.
    const { select, stop, ensureLive } = useWorkflows()
    select('wf-1')
    expect(esInstances).toBe(1)
    stop()
    ensureLive()
    expect(esInstances).toBe(2) // stream reopened
    stop()
  })

  it('reject sends the refinement prompt', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const wf = useWorkflows()
    // a current run must be selected for reject() to post
    wf.current.value = {
      id: 'wf-1', repo: 'o/r', issue_number: 1, issue_title: 't',
      status: 'awaiting_plan_approval', branch: 'b', steps: [],
      current_session_id: null, active_sessions: [], pr_url: null,
      error: null,
    }
    await wf.reject('tighten scope')
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/workflows/wf-1/reject')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      refinement_prompt: 'tighten scope',
    })
    await wf.reject()
    const [, init2] = fetchMock.mock.calls[1]
    expect(JSON.parse((init2 as RequestInit).body as string)).toEqual({
      refinement_prompt: null,
    })
  })
})

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
  useWorkflows().stop()
  useWorkflows().current.value = null
})
afterEach(() => {
  useWorkflows().stop()
  vi.restoreAllMocks()
})

function detail(id: string) {
  return {
    id,
    repo: 'o/r',
    issue_number: 3,
    issue_title: 't',
    status: 'refining',
    branch: 'b',
    steps: [],
    current_session_id: null,
    active_sessions: [],
    round_history: [],
    refine_round_cap: 1,
    refine_max_rounds: 3,
    verify_max_iterations: 3,
    allow_incomplete_answers: false,
    rerunnable: false,
    task_label: 'o/r#3',
    task_link: null,
    pr_url: null,
    error: null,
    artifacts: [],
  }
}

describe('useWorkflows', () => {
  it('refresh populates workflows from the api', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
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

  it('refresh surfaces a request failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('unavailable', { status: 503 })),
    )
    const { error, refresh } = useWorkflows()

    await refresh()

    expect(error.value).toBe('Request failed (503)')
  })

  it('select opens a workflow event stream and applies snapshots', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(detail('wf-1')), { status: 200 })),
    )
    const { select, current } = useWorkflows()
    await select('wf-1')
    expect(esInstances).toBe(1)
    expect(lastEs?.url).toContain('/api/workflows/wf-1/events')
    lastEs?.emit({
      id: 'wf-1',
      repo: 'o/r',
      issue_number: 3,
      issue_title: 't',
      status: 'refining',
      branch: 'b',
      steps: [],
      current_session_id: null,
      active_sessions: [],
      pr_url: null,
      error: null,
    })
    expect(current.value?.status).toBe('refining')
  })

  it('hydrates detail before subscribing for a deep-linked selection', async () => {
    const fetch = vi.fn(
      async () => new Response(JSON.stringify(detail('wf-9')), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetch)
    const { current, select } = useWorkflows()

    const selecting = select('wf-9')

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/workflows/wf-9'),
      expect.objectContaining({ method: 'GET' }),
    )
    expect(esInstances).toBe(0)
    await selecting
    expect(current.value?.id).toBe('wf-9')
    expect(esInstances).toBe(1)
  })

  it('saves a draft against the selected deep-link workflow', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(detail('wf-9')), { status: 200 })),
    )
    const { saveDraft, select } = useWorkflows()
    await select('wf-9')

    await saveDraft({ q1: 'yes' })

    expect(fetch).toHaveBeenLastCalledWith(
      expect.stringContaining('/workflows/wf-9/answers/draft'),
      expect.any(Object),
    )
  })

  it('startList streams the summary list into the sidebar', () => {
    const { workflows, startList, stopList } = useWorkflows()
    startList()
    expect(esInstances).toBe(1)
    expect(lastEs?.url).toContain('/api/workflows/events')
    // A background-created run (Jira, null issue_number) arrives live.
    lastEs?.emit([
      { id: 'wf-9', repo: 'acme/gw', issue_number: null, status: 'refining' },
    ])
    expect(workflows.value.map((w) => w.id)).toEqual(['wf-9'])
    stopList()
    expect(lastEs?.close).toHaveBeenCalled()
  })

  it('applies live snapshots to the sidebar list card status', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
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
    await select('wf-2')
    lastEs?.emit({
      id: 'wf-2',
      repo: 'o/r',
      issue_number: 4,
      issue_title: 't',
      status: 'refining',
      branch: 'b',
      steps: [],
      current_session_id: null,
      active_sessions: [],
      pr_url: null,
      error: null,
    })
    // The list card status advanced from its create-time value, live.
    expect(workflows.value.find((w) => w.id === 'wf-2')?.status).toBe(
      'refining',
    )
  })

  it('stop closes the active EventSource', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(detail('wf-1')), { status: 200 })),
    )
    const { select, stop } = useWorkflows()
    await select('wf-1')
    const closed = lastEs!.close
    stop()
    expect(closed).toHaveBeenCalled()
  })

  it('ensureLive resumes the stream after stop', async () => {
    // Regression: switching views unmounts the panel (stop());
    // remounting must reopen the stream for the selected run, or the
    // UI freezes and never shows the awaiting_input reply gate.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(detail('wf-1')), { status: 200 })),
    )
    const { select, stop, ensureLive } = useWorkflows()
    await select('wf-1')
    expect(esInstances).toBe(1)
    stop()
    ensureLive()
    await Promise.resolve()
    expect(esInstances).toBe(1) // selection is cleared by stop()
    stop()
  })

  it('reject sends the refinement prompt', async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ status: 'ok' }), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const wf = useWorkflows()
    // a current run must be selected for reject() to post
    wf.current.value = {
      id: 'wf-1',
      repo: 'o/r',
      issue_number: 1,
      issue_title: 't',
      status: 'awaiting_plan_approval',
      branch: 'b',
      steps: [],
      current_session_id: null,
      active_sessions: [],
      pr_url: null,
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

  it('surfaces a gate-action failure instead of doing nothing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('no gate awaiting', { status: 409 })),
    )
    const wf = useWorkflows()
    wf.current.value = {
      id: 'wf-1',
      repo: 'o/r',
      issue_number: 1,
      issue_title: 't',
      status: 'awaiting_refine_approval',
      branch: 'b',
      steps: [],
      current_session_id: null,
      active_sessions: [],
      pr_url: null,
      error: null,
    }
    const ok = await wf.reject()
    expect(ok).toBe(false)
    expect(wf.error.value).toBeTruthy()
  })

  it('pollActiveStep posts to the poll endpoint and applies the response', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith('/api/workflows/wf-1/poll')
        ? new Response(
            JSON.stringify({
              id: 'wf-1',
              repo: 'o/r',
              issue_number: 1,
              issue_title: 't',
              status: 'coding',
              branch: 'b',
              steps: [],
              current_session_id: null,
              active_sessions: [],
              pr_url: null,
              error: null,
            }),
            { status: 200 },
          )
        : new Response(JSON.stringify([]), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const wf = useWorkflows()
    wf.current.value = {
      id: 'wf-1',
      repo: 'o/r',
      issue_number: 1,
      issue_title: 't',
      status: 'designing',
      branch: 'b',
      steps: [],
      current_session_id: null,
      active_sessions: [],
      pr_url: null,
      error: null,
    }

    const ok = await wf.pollActiveStep()

    expect(ok).toBe(true)
    expect(wf.current.value?.status).toBe('coding')
  })

  it('pollActiveStep is a no-op with nothing selected', async () => {
    const wf = useWorkflows()
    wf.current.value = null
    wf.stop()
    const ok = await wf.pollActiveStep()
    expect(ok).toBe(false)
  })

  it('rerun posts to the rerun endpoint and refreshes the list', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith('/rerun')
        ? new Response(JSON.stringify({ workflow_id: 'wf-2' }), {
            status: 200,
          })
        : new Response(JSON.stringify([]), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const wf = useWorkflows()
    await wf.rerun('wf-1')
    const rerunCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/api/workflows/wf-1/rerun'),
    )
    expect(rerunCall).toBeTruthy()
    expect(rerunCall?.[1]).toMatchObject({ method: 'POST' })
  })

  it('rerun clears the selected run when it was the target', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })),
    )
    const wf = useWorkflows()
    wf.current.value = {
      id: 'wf-1',
      repo: 'o/r',
      issue_number: 3,
      issue_title: 'T',
      status: 'coding',
      branch: 'b',
      steps: [],
      current_session_id: null,
      active_sessions: [],
      round_history: [],
      refine_round_cap: 1,
      refine_max_rounds: 1,
      verify_max_iterations: 1,
      allow_incomplete_answers: false,
      rerunnable: true,
      pr_url: null,
      error: null,
    }

    await wf.rerun('wf-1')

    expect(wf.current.value).toBeNull()
  })

  it('rerun surfaces a request failure instead of doing nothing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('nope', { status: 403 })),
    )
    const wf = useWorkflows()
    await wf.rerun('wf-1')
    expect(wf.error.value).toBeTruthy()
  })
})

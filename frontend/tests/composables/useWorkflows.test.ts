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
})

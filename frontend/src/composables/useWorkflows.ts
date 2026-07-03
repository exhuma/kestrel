import { ref } from 'vue'
import { api, API_BASE, ApiError } from '../api'
import type { SessionEvent } from '../types/sessions'
import type { WorkflowDetail, WorkflowSummary } from '../types/workflows'

const workflows = ref<WorkflowSummary[]>([])
const current = ref<WorkflowDetail | null>(null)
const events = ref<SessionEvent[]>([])
const error = ref<string | null>(null)

let detailSource: EventSource | null = null
let source: EventSource | null = null

function describe(e: unknown): string {
  if (e instanceof ApiError) return `Request failed (${e.status})`
  if (e instanceof Error) return e.message
  return 'Unexpected error'
}

export function useWorkflows() {
  async function refresh(): Promise<void> {
    workflows.value = await api.get<WorkflowSummary[]>('/api/workflows')
  }

  function applyDetail(detail: WorkflowDetail): void {
    current.value = detail
  }

  // Telemetry is on-demand now: the workflow view stays compact and only
  // streams a session's raw events when the user opens its chip.
  function streamSession(sessionId: string): void {
    events.value = []
    if (source) source.close()
    source = new EventSource(`${API_BASE}/api/sessions/${sessionId}/events`)
    source.onmessage = (e) => {
      events.value.push(JSON.parse(e.data) as SessionEvent)
    }
  }

  function closeSession(): void {
    if (source) {
      source.close()
      source = null
    }
    events.value = []
  }

  function select(id: string): void {
    // Push, don't poll: the backend streams a fresh snapshot on every
    // real state change, so the UI never re-renders (and never clobbers
    // in-progress form input) on an idle interval.
    stopDetail()
    detailSource = new EventSource(`${API_BASE}/api/workflows/${id}/events`)
    detailSource.onmessage = (e) => {
      applyDetail(JSON.parse(e.data) as WorkflowDetail)
    }
  }

  function ensureLive(): void {
    // Re-arm the event stream after stop() so a remounted panel keeps
    // tracking the already-selected run. Without this, the UI freezes
    // on the pre-unmount state and never surfaces awaiting_* gates.
    if (current.value && !detailSource) select(current.value.id)
  }

  async function createWorkflow(repo: string, issueNumber: number): Promise<string | null> {
    error.value = null
    try {
      const out = await api.post<{ workflow_id: string }>('/api/workflows', {
        repo,
        issue_number: issueNumber,
      })
      await refresh()
      select(out.workflow_id)
      return out.workflow_id
    } catch (e) {
      error.value = describe(e)
      return null
    }
  }

  async function reply(text: string): Promise<void> {
    if (current.value) await api.post(`/api/workflows/${current.value.id}/reply`, { text })
  }

  async function submitAnswers(
    answers: Record<string, unknown>,
  ): Promise<void> {
    if (current.value)
      await api.post(`/api/workflows/${current.value.id}/answers`, {
        answers,
      })
  }

  async function saveDraft(
    answers: Record<string, unknown>,
  ): Promise<void> {
    if (current.value)
      await api.post(`/api/workflows/${current.value.id}/answers/draft`, {
        answers,
      })
  }

  async function approve(deliverable?: string): Promise<void> {
    if (current.value)
      await api.post(`/api/workflows/${current.value.id}/approve`, { deliverable: deliverable ?? null })
  }

  async function reject(refinementPrompt?: string): Promise<void> {
    if (current.value)
      await api.post(`/api/workflows/${current.value.id}/reject`, {
        refinement_prompt: refinementPrompt ?? null,
      })
  }

  function stopDetail(): void {
    if (detailSource) {
      detailSource.close()
      detailSource = null
    }
  }

  function stop(): void {
    stopDetail()
    if (source) {
      source.close()
      source = null
    }
  }

  async function remove(id: string): Promise<void> {
    error.value = null
    try {
      await api.del(`/api/workflows/${id}`)
      if (current.value?.id === id) {
        stop()
        current.value = null
      }
      await refresh()
    } catch (e) {
      error.value = describe(e)
    }
  }

  return { workflows, current, events, error, refresh, select, ensureLive, streamSession, closeSession, createWorkflow, reply, submitAnswers, saveDraft, approve, reject, stop, remove }
}

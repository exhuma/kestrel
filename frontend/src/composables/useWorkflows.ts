import { ref } from 'vue'
import { api, API_BASE, ApiError } from '../api'
import type { SessionEvent } from '../types/sessions'
import type { WorkflowDetail, WorkflowSummary } from '../types/workflows'

const workflows = ref<WorkflowSummary[]>([])
const current = ref<WorkflowDetail | null>(null)
const events = ref<SessionEvent[]>([])
const error = ref<string | null>(null)

let source: EventSource | null = null
let poll: ReturnType<typeof setInterval> | null = null

function describe(e: unknown): string {
  if (e instanceof ApiError) return `Request failed (${e.status})`
  if (e instanceof Error) return e.message
  return 'Unexpected error'
}

export function useWorkflows() {
  async function refresh(): Promise<void> {
    workflows.value = await api.get<WorkflowSummary[]>('/api/workflows')
  }

  async function loadDetail(id: string): Promise<void> {
    const detail = await api.get<WorkflowDetail>(`/api/workflows/${id}`)
    // Re-subscribe to the live feed when the active step's session
    // changes, or when the previous subscription was torn down by
    // stop() (e.g. the panel was unmounted and remounted).
    if (detail.current_session_id &&
        (!source ||
          detail.current_session_id !== current.value?.current_session_id)) {
      watchSession(detail.current_session_id)
    }
    current.value = detail
  }

  function watchSession(sessionId: string): void {
    events.value = []
    if (source) source.close()
    source = new EventSource(`${API_BASE}/api/sessions/${sessionId}/events`)
    source.onmessage = (e) => {
      events.value.push(JSON.parse(e.data) as SessionEvent)
    }
  }

  function select(id: string): void {
    if (poll) clearInterval(poll)
    void loadDetail(id)
    poll = setInterval(() => void loadDetail(id), 1500)
  }

  function ensureLive(): void {
    // Re-arm polling and the event stream after stop() so a
    // remounted panel keeps tracking the already-selected run.
    // Without this, the UI freezes on the pre-unmount state and
    // never surfaces awaiting_input / awaiting_approval gates.
    if (current.value && !poll) select(current.value.id)
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

  function stop(): void {
    if (poll) {
      clearInterval(poll)
      poll = null
    }
    if (source) {
      source.close()
      source = null
    }
  }

  return { workflows, current, events, error, refresh, select, ensureLive, createWorkflow, reply, submitAnswers, approve, reject, stop }
}

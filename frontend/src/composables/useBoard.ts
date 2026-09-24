import { ref } from 'vue'
import { api, API_BASE, ApiError } from '../api'
import type {
  BoardInterventionRequest,
  BoardSnapshot,
  BoardWorkflowSummary,
  CardAction,
  WorkCardSummary,
} from '../types/workflows'

// Additive alongside useWorkflows.ts (the old driver's composable) — the
// board domain has its own collection/snapshot/intervention surface under
// /api/board, never replacing the fixed-step one (feature 026, US6).

const workflows = ref<BoardWorkflowSummary[]>([])
const current = ref<BoardSnapshot | null>(null)
const selectedId = ref<string | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

let listSource: EventSource | null = null
let detailSource: EventSource | null = null

function describe(e: unknown): string {
  if (e instanceof ApiError) return `Request failed (${e.status})`
  if (e instanceof Error) return e.message
  return 'Unexpected error'
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    workflows.value = await api.get<BoardWorkflowSummary[]>(
      '/api/board/workflows',
    )
  } catch (e) {
    error.value = describe(e)
  } finally {
    loading.value = false
  }
}

function startList(): void {
  if (listSource) return
  listSource = new EventSource(`${API_BASE}/api/board/workflows/events`)
  listSource.onmessage = (e) => {
    workflows.value = JSON.parse(e.data) as BoardWorkflowSummary[]
  }
}

function stopList(): void {
  if (listSource) {
    listSource.close()
    listSource = null
  }
}

function stopDetail(): void {
  if (detailSource) {
    detailSource.close()
    detailSource = null
  }
}

async function fetchSnapshot(id: string): Promise<boolean> {
  loading.value = true
  error.value = null
  try {
    const snapshot = await api.get<BoardSnapshot>(
      `/api/board/workflows/${id}/board`,
    )
    if (selectedId.value !== id) return false
    current.value = snapshot
    return true
  } catch (e) {
    if (selectedId.value === id) error.value = describe(e)
    return false
  } finally {
    if (selectedId.value === id) loading.value = false
  }
}

function openDetailStream(id: string): void {
  detailSource = new EventSource(
    `${API_BASE}/api/board/workflows/${id}/board/events`,
  )
  detailSource.onmessage = (e) => {
    const snapshot = JSON.parse(e.data) as BoardSnapshot
    if (selectedId.value === id && snapshot.id === id) {
      current.value = snapshot
    }
  }
}

async function select(id: string): Promise<void> {
  // Push, not poll: the server streams a fresh snapshot on every
  // committed board mutation, the same convention as useWorkflows.
  stopDetail()
  selectedId.value = id
  const ok = await fetchSnapshot(id)
  if (ok && selectedId.value === id) openDetailStream(id)
}

function stop(): void {
  stopDetail()
  selectedId.value = null
}

// Every intervention echoes the snapshot's own revision back as
// expected_revision (optimistic concurrency) — a stale value is a 409 the
// caller surfaces on the error banner rather than silently no-op-ing.
async function applyIntervention(
  cardId: string,
  action: CardAction,
  decision?: string,
): Promise<WorkCardSummary | null> {
  const workflowId = current.value?.id
  const revision = current.value?.revision
  if (!workflowId || revision === undefined) return null
  error.value = null
  try {
    const body: BoardInterventionRequest = {
      action,
      expected_revision: revision,
      decision: decision ?? null,
    }
    return await api.post<WorkCardSummary>(
      `/api/board/workflows/${workflowId}/cards/${cardId}/interventions`,
      body,
    )
  } catch (e) {
    error.value = describe(e)
    return null
  }
}

export function useBoard() {
  return {
    workflows,
    current,
    selectedId,
    loading,
    error,
    refresh,
    startList,
    stopList,
    select,
    stop,
    applyIntervention,
  }
}

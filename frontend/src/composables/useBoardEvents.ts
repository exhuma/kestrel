/**
 * One workflow's board event history — the narrative feed's data source
 * (feature 029, US2).
 *
 * There is nothing to subscribe to. The per-workflow SSE stream carries
 * the whole *snapshot* and never incremental events
 * (`backend/app/routers/board.py`), and the history itself is a plain REST
 * list. So "live feed" here means: fetch once, then re-fetch whenever the
 * snapshot's `revision` ticks. Every committed board mutation bumps that
 * revision, so it is exactly the signal the feed needs and costs one
 * request per real change rather than a poll.
 *
 * Module-level singleton keyed per workflow, per the project's no-Pinia
 * convention.
 */
import { ref, watch, type Ref } from 'vue'
import { api, ApiError } from '../api'
import type { BoardEvent } from '../types/workflows'
import { useBoard } from './useBoard'

const events = ref<BoardEvent[]>([])
const error = ref<string | null>(null)
const loading = ref(false)

/** The workflow the above state describes; `null` when nothing is open. */
let subscribedId: string | null = null
let stopWatch: (() => void) | null = null

/** Identity for de-duplication. Board events carry no id of their own, so
 *  the feed keys on the tuple that makes one event distinct. Two genuinely
 *  identical events at the same timestamp are indistinguishable by any
 *  means available to the client — collapsing them is the honest choice,
 *  and preferable to the duplicate rows a re-fetch would otherwise add. */
function identity(e: BoardEvent): string {
  return [e.created_at ?? '', e.event_type, e.card_id ?? '', e.payload].join(
    '\0',
  )
}

/** Merge *incoming* into the known history, keeping the server's order and
 *  dropping entries already shown. The endpoint returns the full history
 *  every time, so without this every tick would re-append everything. */
function merge(incoming: BoardEvent[]): BoardEvent[] {
  const seen = new Set<string>()
  const merged: BoardEvent[] = []
  for (const e of incoming) {
    const key = identity(e)
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(e)
  }
  return merged
}

async function fetchEvents(id: string): Promise<void> {
  loading.value = true
  try {
    const incoming = await api.get<BoardEvent[]>(
      `/api/board/workflows/${id}/events`,
    )
    // A late response for a workflow the operator has already left must
    // not overwrite the one they are looking at now.
    if (subscribedId !== id) return
    events.value = merge(incoming)
    error.value = null
  } catch (e) {
    if (subscribedId !== id) return
    error.value =
      e instanceof ApiError
        ? `Could not load the history (${e.status}).`
        : 'Could not reach the backend to load the history.'
  } finally {
    if (subscribedId === id) loading.value = false
  }
}

/** Start following *id*'s history: fetch it now, then re-fetch on every
 *  snapshot revision tick. Safe to call repeatedly for the same id. */
function start(id: string): void {
  if (subscribedId === id) return
  stop()
  subscribedId = id
  const { current } = useBoard()
  stopWatch = watch(
    () => current.value?.revision,
    () => {
      if (current.value?.id === id) void fetchEvents(id)
    },
  )
  void fetchEvents(id)
}

/** Stop following and clear the history, so the next request's cockpit
 *  never briefly shows the previous one's narrative. */
function stop(): void {
  stopWatch?.()
  stopWatch = null
  subscribedId = null
  events.value = []
  error.value = null
  loading.value = false
}

export function useBoardEvents(): {
  events: Ref<BoardEvent[]>
  error: Ref<string | null>
  loading: Ref<boolean>
  start: (id: string) => void
  stop: () => void
} {
  return { events, error, loading, start, stop }
}

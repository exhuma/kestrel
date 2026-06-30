export interface SessionSummary {
  session_id: string
  status: string
  event_count: number
}

export interface SessionEvent {
  type: string
  session_id: string | null
  raw: Record<string, unknown>
}

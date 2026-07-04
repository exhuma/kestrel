export interface SessionSummary {
  session_id: string
  status: string
  event_count: number
  /** ISO timestamp of when the session started, if known. */
  created_at: string | null
  /** The run that used this session ("repo#issue"), or null. */
  workflow: string | null
}

export interface SessionEvent {
  type: string
  session_id: string | null
  raw: Record<string, unknown>
}

export interface SessionSummary {
  session_id: string
  status: string
  event_count: number
  /** ISO timestamp of when the session started, if known. */
  created_at: string | null
  /** The run that used this session ("repo#issue"), or null. */
  workflow: string | null
}

/**
 * One canonical, backend-agnostic timeline event.
 *
 * Every backend (claude CLI, opencode, plain LLMs) maps its native
 * output onto this shape server-side, so the UI never parses any one
 * backend's raw event format. Only the fields relevant to `kind` are
 * populated; `native` preserves the original payload for the raw view.
 */
export interface SessionEvent {
  kind: string
  session_id: string | null
  text?: string | null
  tool_name?: string | null
  tool_input?: Record<string, unknown> | null
  tool_summary?: string | null
  is_error?: boolean
  tokens?: number | null
  subtype?: string | null
  summary?: string | null
  model?: string | null
  tools?: string[] | null
  /** MCP servers reported on a system init event, each `{name, status}`. */
  mcp_servers?: { name?: string; status?: string }[] | null
  duration_ms?: number | null
  status?: string | null
  native?: Record<string, unknown>
}

import type { SessionEvent } from '../types/sessions'

export type EventViewKind =
  | { kind: 'chat'; role: 'assistant' | 'user'; text: string }
  | { kind: 'tool_call'; name: string; input: string; preface?: string }
  | { kind: 'tool_result'; content: string; isError: boolean }
  | { kind: 'thinking'; tokens: number }
  | { kind: 'system'; subtype: string; summary: string }
  | { kind: 'rate_limit'; status: string }
  | {
      kind: 'result'
      success: boolean
      durationMs: number | null
      summary: string | null
    }
  | { kind: 'unknown' }

export interface EventVM {
  raw: Record<string, unknown>
  type: string
  view: EventViewKind
}

/**
 * Render the init event's MCP servers as "name (status), …", or the
 * literal "none" when no servers were reported — so the telemetry makes
 * plain whether a configured MCP (e.g. quartermaster) actually loaded
 * into this headless session.
 */
export function mcpSummary(e: SessionEvent): string {
  const servers = Array.isArray(e.mcp_servers) ? e.mcp_servers : []
  if (!servers.length) return 'none'
  return servers
    .map((m) => {
      const name = typeof m.name === 'string' ? m.name : '?'
      const status = typeof m.status === 'string' ? m.status : ''
      return status ? `${name} (${status})` : name
    })
    .join(', ')
}

/**
 * Project a canonical event onto a typed view model. The backend has
 * already normalized every backend's native output into the canonical
 * fields, so this is a near-direct field map. Never throws.
 */
export function toViewModel(e: SessionEvent): EventVM {
  const raw = e.native ?? {}
  const nativeType =
    typeof raw.type === 'string' ? (raw.type as string) : e.kind
  let view: EventViewKind
  switch (e.kind) {
    case 'assistant_text':
      view = { kind: 'chat', role: 'assistant', text: e.text ?? '' }
      break
    case 'user_text':
      view = { kind: 'chat', role: 'user', text: e.text ?? '' }
      break
    case 'tool_use':
      view = {
        kind: 'tool_call',
        name: e.tool_name ?? '',
        input: e.tool_summary ?? '',
        preface: e.text || undefined,
      }
      break
    case 'tool_result':
      view = {
        kind: 'tool_result',
        content: e.text ?? '',
        isError: !!e.is_error,
      }
      break
    case 'thinking':
      view = { kind: 'thinking', tokens: e.tokens ?? 0 }
      break
    case 'system': {
      const subtype = e.subtype ?? 'unknown'
      // The init frame is where MCP availability is knowable.
      const summary =
        subtype === 'init' ? `MCP: ${mcpSummary(e)}` : (e.summary ?? subtype)
      view = { kind: 'system', subtype, summary }
      break
    }
    case 'rate_limit':
      view = { kind: 'rate_limit', status: e.status ?? 'unknown' }
      break
    case 'result':
      view = {
        kind: 'result',
        success: !e.is_error,
        durationMs: e.duration_ms ?? null,
        summary: e.text ?? null,
      }
      break
    default:
      view = { kind: 'unknown' }
  }
  return { raw, type: nativeType, view }
}

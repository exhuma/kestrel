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

interface ContentBlock {
  type?: string
  text?: string
  name?: string
  input?: Record<string, unknown>
  content?: unknown
  is_error?: boolean
}

function messageContent(raw: Record<string, unknown>): ContentBlock[] | null {
  const message = raw.message as { content?: unknown } | undefined
  const content = message?.content
  return Array.isArray(content) ? (content as ContentBlock[]) : null
}

function toolInputSummary(input: Record<string, unknown> | undefined): string {
  if (!input) return ''
  const arg = input.file_path ?? input.path ?? input.command
  return typeof arg === 'string' ? arg : JSON.stringify(input)
}

function classifyAssistant(raw: Record<string, unknown>): EventViewKind {
  const content = messageContent(raw)
  if (!content) return { kind: 'unknown' }
  const toolUse = content.find((c) => c.type === 'tool_use')
  const texts = content
    .filter((c) => c.type === 'text' && typeof c.text === 'string')
    .map((c) => c.text as string)
  if (toolUse && typeof toolUse.name === 'string') {
    return {
      kind: 'tool_call',
      name: toolUse.name,
      input: toolInputSummary(toolUse.input),
      preface: texts.length ? texts.join(' ') : undefined,
    }
  }
  if (texts.length) return { kind: 'chat', role: 'assistant', text: texts.join('\n') }
  return { kind: 'unknown' }
}

function classifyUser(raw: Record<string, unknown>): EventViewKind {
  const content = messageContent(raw)
  if (!content) return { kind: 'unknown' }
  const toolResult = content.find((c) => c.type === 'tool_result')
  if (toolResult) {
    return {
      kind: 'tool_result',
      content:
        typeof toolResult.content === 'string'
          ? toolResult.content
          : JSON.stringify(toolResult.content),
      isError: !!toolResult.is_error,
    }
  }
  const texts = content
    .filter((c) => c.type === 'text' && typeof c.text === 'string')
    .map((c) => c.text as string)
  if (texts.length) return { kind: 'chat', role: 'user', text: texts.join('\n') }
  return { kind: 'unknown' }
}

/**
 * Render the init event's MCP servers as "name (status), …", or the
 * literal "none" when the CLI reported no servers — so the telemetry
 * makes plain whether a configured MCP (e.g. quartermaster) actually
 * loaded into this headless session.
 */
export function mcpSummary(raw: Record<string, unknown>): string {
  const servers = Array.isArray(raw.mcp_servers)
    ? (raw.mcp_servers as { name?: unknown; status?: unknown }[])
    : []
  if (!servers.length) return 'none'
  return servers
    .map((m) => {
      const name = typeof m.name === 'string' ? m.name : '?'
      const status = typeof m.status === 'string' ? m.status : ''
      return status ? `${name} (${status})` : name
    })
    .join(', ')
}

function classifySystem(raw: Record<string, unknown>): EventViewKind {
  const subtype = typeof raw.subtype === 'string' ? raw.subtype : 'unknown'
  if (subtype === 'thinking_tokens') {
    const tokens = raw.estimated_tokens
    return { kind: 'thinking', tokens: typeof tokens === 'number' ? tokens : 0 }
  }
  if (subtype === 'init') {
    // The init frame is where MCP availability is knowable.
    return { kind: 'system', subtype, summary: `MCP: ${mcpSummary(raw)}` }
  }
  const summary =
    (typeof raw.hook_name === 'string' && raw.hook_name) ||
    (typeof raw.status_category === 'string' && raw.status_category) ||
    subtype
  return { kind: 'system', subtype, summary }
}

function classifyResult(raw: Record<string, unknown>): EventViewKind {
  const durationMs = typeof raw.duration_ms === 'number' ? raw.duration_ms : null
  const summary = typeof raw.result === 'string' ? raw.result : null
  return { kind: 'result', success: !raw.is_error, durationMs, summary }
}

function classifyRateLimit(raw: Record<string, unknown>): EventViewKind {
  const info = raw.rate_limit_info as { status?: unknown } | undefined
  const status = typeof info?.status === 'string' ? info.status : 'unknown'
  return { kind: 'rate_limit', status }
}

/** Classify a raw stream-json event into a typed view model. Never throws. */
export function toViewModel(e: SessionEvent): EventVM {
  const raw = e.raw
  let view: EventViewKind
  switch (e.type) {
    case 'assistant':
      view = classifyAssistant(raw)
      break
    case 'user':
      view = classifyUser(raw)
      break
    case 'system':
      view = classifySystem(raw)
      break
    case 'result':
      view = classifyResult(raw)
      break
    case 'rate_limit_event':
      view = classifyRateLimit(raw)
      break
    default:
      view = { kind: 'unknown' }
  }
  return { raw, type: e.type, view }
}

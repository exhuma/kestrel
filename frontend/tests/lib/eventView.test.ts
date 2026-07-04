import { describe, it, expect } from 'vitest'
import { toViewModel } from '../../src/lib/eventView'
import type { SessionEvent } from '../../src/types/sessions'

/**
 * Build a canonical SessionEvent for a test. The backend now normalizes
 * every backend's native stream into these canonical fields (that
 * mapping is covered by the backend's test_models.py); here we assert
 * the canonical -> view-model projection.
 */
function ev(partial: Partial<SessionEvent> & { kind: string }): SessionEvent {
  return { session_id: 's1', ...partial }
}

describe('toViewModel', () => {
  it('classifies an assistant text message as chat', () => {
    const vm = toViewModel(ev({
      kind: 'assistant_text',
      text: 'Let me check the existing test conventions.',
    }))
    expect(vm.view).toEqual({
      kind: 'chat', role: 'assistant',
      text: 'Let me check the existing test conventions.',
    })
  })

  it('classifies a tool_use event as tool_call', () => {
    const vm = toViewModel(ev({
      kind: 'tool_use', tool_name: 'Read',
      tool_summary: '/home/exhuma/work/agent-dispatcher/backend/app/main.py',
    }))
    expect(vm.view).toEqual({
      kind: 'tool_call', name: 'Read',
      input: '/home/exhuma/work/agent-dispatcher/backend/app/main.py',
      preface: undefined,
    })
  })

  it('keeps preceding text as a preface on a tool_call', () => {
    const vm = toViewModel(ev({
      kind: 'tool_use', tool_name: 'Read', tool_summary: 'x.py',
      text: 'Checking the file first.',
    }))
    expect(vm.view).toEqual({
      kind: 'tool_call', name: 'Read', input: 'x.py',
      preface: 'Checking the file first.',
    })
  })

  it('classifies a tool_result event', () => {
    const vm = toViewModel(ev({
      kind: 'tool_result', text: 'file contents here', is_error: false,
    }))
    expect(vm.view).toEqual({
      kind: 'tool_result', content: 'file contents here', isError: false,
    })
  })

  it('classifies a plain user text message as chat', () => {
    const vm = toViewModel(ev({ kind: 'user_text', text: 'Blue, please' }))
    expect(vm.view).toEqual({ kind: 'chat', role: 'user', text: 'Blue, please' })
  })

  it('classifies thinking as thinking', () => {
    const vm = toViewModel(ev({ kind: 'thinking', tokens: 150 }))
    expect(vm.view).toEqual({ kind: 'thinking', tokens: 150 })
  })

  it('classifies other system subtypes generically', () => {
    const vm = toViewModel(ev({
      kind: 'system', subtype: 'hook_started', summary: 'SessionStart:startup',
    }))
    expect(vm.view).toEqual({
      kind: 'system', subtype: 'hook_started',
      summary: 'SessionStart:startup',
    })
  })

  it('surfaces MCP servers on the init event', () => {
    const vm = toViewModel(ev({
      kind: 'system', subtype: 'init', model: 'sonnet',
      mcp_servers: [{ name: 'quartermaster', status: 'connected' }],
    }))
    expect(vm.view).toEqual({
      kind: 'system', subtype: 'init',
      summary: 'MCP: quartermaster (connected)',
    })
  })

  it('reports MCP: none when the init event lists no servers', () => {
    const vm = toViewModel(ev({
      kind: 'system', subtype: 'init', model: 'sonnet', mcp_servers: [],
    }))
    expect(vm.view).toEqual({
      kind: 'system', subtype: 'init', summary: 'MCP: none',
    })
  })

  it('classifies rate_limit', () => {
    const vm = toViewModel(ev({ kind: 'rate_limit', status: 'allowed_warning' }))
    expect(vm.view).toEqual({ kind: 'rate_limit', status: 'allowed_warning' })
  })

  it('classifies a successful result', () => {
    const vm = toViewModel(ev({
      kind: 'result', is_error: false,
      duration_ms: 19164, text: 'Implemented using config.yaml',
    }))
    expect(vm.view).toEqual({
      kind: 'result', success: true, durationMs: 19164,
      summary: 'Implemented using config.yaml',
    })
  })

  it('classifies a failed result', () => {
    const vm = toViewModel(ev({
      kind: 'result', is_error: true, duration_ms: 500,
    }))
    expect(vm.view).toEqual({
      kind: 'result', success: false, durationMs: 500, summary: null,
    })
  })

  it('falls back to unknown for an unrecognised kind', () => {
    const vm = toViewModel(ev({
      kind: 'unknown', native: { type: 'totally_new_event_type', foo: 'bar' },
    }))
    expect(vm.view).toEqual({ kind: 'unknown' })
    expect(vm.raw).toEqual({ type: 'totally_new_event_type', foo: 'bar' })
  })

  it('carries the native type and raw payload through', () => {
    const native = { type: 'result', subtype: 'success', is_error: false }
    const vm = toViewModel(ev({ kind: 'result', is_error: false, native }))
    expect(vm.type).toBe('result')
    expect(vm.raw).toEqual(native)
  })
})

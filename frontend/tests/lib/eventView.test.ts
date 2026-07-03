import { describe, it, expect } from 'vitest'
import { toViewModel } from '../../src/lib/eventView'
import type { SessionEvent } from '../../src/types/sessions'

function ev(raw: Record<string, unknown>): SessionEvent {
  return {
    type: raw.type as string,
    session_id: (raw.session_id as string) ?? null,
    raw,
  }
}

describe('toViewModel', () => {
  it('classifies an assistant text message as chat', () => {
    const vm = toViewModel(ev({
      type: 'assistant',
      message: {
        model: 'claude-sonnet-5', role: 'assistant',
        content: [{
          type: 'text',
          text: 'Let me check the existing test conventions.',
        }],
      },
    }))
    expect(vm.view).toEqual({
      kind: 'chat', role: 'assistant',
      text: 'Let me check the existing test conventions.',
    })
  })

  it('classifies an assistant tool_use message as tool_call', () => {
    const vm = toViewModel(ev({
      type: 'assistant',
      message: {
        model: 'claude-sonnet-5', role: 'assistant',
        content: [{
          type: 'tool_use',
          id: 'toolu_01DVZSbprR4Ay1eb9PSREox5',
          name: 'Read',
          input: { file_path: '/home/exhuma/work/agent-dispatcher/backend/app/main.py' },
        }],
      },
    }))
    expect(vm.view).toEqual({
      kind: 'tool_call', name: 'Read',
      input: '/home/exhuma/work/agent-dispatcher/backend/app/main.py',
      preface: undefined,
    })
  })

  it('keeps preceding text as a preface on a tool_call', () => {
    const vm = toViewModel(ev({
      type: 'assistant',
      message: {
        role: 'assistant',
        content: [
          { type: 'text', text: 'Checking the file first.' },
          { type: 'tool_use', name: 'Read', input: { path: 'x.py' } },
        ],
      },
    }))
    expect(vm.view).toEqual({
      kind: 'tool_call', name: 'Read', input: 'x.py',
      preface: 'Checking the file first.',
    })
  })

  it('classifies a user tool_result message', () => {
    const vm = toViewModel(ev({
      type: 'user',
      message: {
        role: 'user',
        content: [{
          type: 'tool_result',
          tool_use_id: 'toolu_01DVZSbprR4Ay1eb9PSREox5',
          content: 'file contents here',
        }],
      },
    }))
    expect(vm.view).toEqual({
      kind: 'tool_result', content: 'file contents here', isError: false,
    })
  })

  it('classifies a plain user text message as chat', () => {
    const vm = toViewModel(ev({
      type: 'user',
      message: { role: 'user', content: [{ type: 'text', text: 'Blue, please' }] },
    }))
    expect(vm.view).toEqual({ kind: 'chat', role: 'user', text: 'Blue, please' })
  })

  it('classifies system thinking_tokens as thinking', () => {
    const vm = toViewModel(ev({
      type: 'system', subtype: 'thinking_tokens',
      estimated_tokens: 150, estimated_tokens_delta: 100,
      uuid: '14181bf3-4bc7-45f1-b8b8-73cd55e67e5f',
    }))
    expect(vm.view).toEqual({ kind: 'thinking', tokens: 150 })
  })

  it('classifies other system subtypes generically', () => {
    const vm = toViewModel(ev({
      type: 'system', subtype: 'hook_started',
      hook_id: 'e3ab1542-a99e-4c17-9f1c-739b3627e937',
      hook_name: 'SessionStart:startup',
    }))
    expect(vm.view).toEqual({
      kind: 'system', subtype: 'hook_started',
      summary: 'SessionStart:startup',
    })
  })

  it('classifies rate_limit_event', () => {
    const vm = toViewModel(ev({
      type: 'rate_limit_event',
      rate_limit_info: {
        status: 'allowed_warning', resetsAt: 1783027200,
        rateLimitType: 'five_hour', utilization: 0.9,
      },
    }))
    expect(vm.view).toEqual({ kind: 'rate_limit', status: 'allowed_warning' })
  })

  it('classifies a successful result', () => {
    const vm = toViewModel(ev({
      type: 'result', subtype: 'success', is_error: false,
      duration_ms: 19164, result: 'Implemented using config.yaml',
    }))
    expect(vm.view).toEqual({
      kind: 'result', success: true, durationMs: 19164,
      summary: 'Implemented using config.yaml',
    })
  })

  it('classifies a failed result', () => {
    const vm = toViewModel(ev({
      type: 'result', subtype: 'error_max_turns', is_error: true,
      duration_ms: 500,
    }))
    expect(vm.view).toEqual({
      kind: 'result', success: false, durationMs: 500, summary: null,
    })
  })

  it('falls back to unknown for an unrecognised type', () => {
    const vm = toViewModel(ev({ type: 'totally_new_event_type', foo: 'bar' }))
    expect(vm.view).toEqual({ kind: 'unknown' })
    expect(vm.raw).toEqual({ type: 'totally_new_event_type', foo: 'bar' })
  })

  it('falls back to unknown for a malformed assistant message', () => {
    const vm = toViewModel(ev({ type: 'assistant', message: {} }))
    expect(vm.view).toEqual({ kind: 'unknown' })
  })

  it('always carries the original type and raw payload', () => {
    const raw = { type: 'result', subtype: 'success', is_error: false }
    const vm = toViewModel(ev(raw))
    expect(vm.type).toBe('result')
    expect(vm.raw).toEqual(raw)
  })
})

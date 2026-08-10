import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import RoundChips from '../../src/components/RoundChips.vue'
import type { RoundChip } from '../../src/types/workflows'

export function chip(over: Partial<RoundChip>): RoundChip {
  return {
    step: 'refine',
    round_index: 0,
    profile_id: 'coordinator',
    label: 'Coordinator',
    badge: 'sys',
    session_id: 's1',
    status: 'idle',
    error: null,
    retired_at: '2026-01-01T00:00:00Z',
    ...over,
  }
}

function mountWith(roundHistory: RoundChip[]) {
  return mount(
    RoundChips,
    withVuetify({
      props: { roundHistory, activeSessions: [], expandedSessionId: null },
    }),
  )
}

describe('RoundChips grouping and icons', () => {
  it('renders a divider between consecutive round groups', () => {
    const wrapper = mountWith([
      chip({ profile_id: 'coordinator', round_index: 0 }),
      chip({ profile_id: 'writer', round_index: 1 }),
    ])
    expect(wrapper.findAllComponents({ name: 'VDivider' })).toHaveLength(1)
  })

  it('does not add a divider within one round group', () => {
    const wrapper = mountWith([
      chip({ profile_id: 'a', round_index: 0 }),
      chip({ profile_id: 'b', round_index: 0 }),
    ])
    expect(wrapper.findAllComponents({ name: 'VDivider' })).toHaveLength(0)
  })

  it('renders a check icon for an idle retired chip', () => {
    const wrapper = mountWith([chip({ status: 'idle' })])
    const icon = wrapper.findComponent({ name: 'VIcon' })
    expect(icon.props('icon')).toBe('$checkCircle')
  })

  it('renders an alert icon for an errored retired chip', () => {
    const wrapper = mountWith([chip({ status: 'error', error: 'boom' })])
    const icon = wrapper.findComponent({ name: 'VIcon' })
    expect(icon.props('icon')).toBe('$alertCircle')
  })
})

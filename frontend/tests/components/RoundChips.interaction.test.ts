import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import RoundChips from '../../src/components/RoundChips.vue'
import type { StepSession } from '../../src/types/workflows'
import { chip } from './RoundChips.test'

function live(over: Partial<StepSession>): StepSession {
  return {
    profile_id: 'designer',
    label: 'Designer',
    badge: 'agent',
    session_id: 's9',
    status: 'running',
    activity: null,
    error: null,
    ...over,
  }
}

describe('RoundChips interaction', () => {
  it('disables click-through for a chip with no session id', () => {
    const wrapper = mount(
      RoundChips,
      withVuetify({
        props: {
          roundHistory: [chip({ session_id: null })],
          activeSessions: [],
          expandedSessionId: null,
        },
      }),
    )
    const vchip = wrapper.findComponent({ name: 'VChip' })
    expect(vchip.props('disabled')).toBe(true)
  })

  it('emits toggle-session with the chip session id on click', async () => {
    const wrapper = mount(
      RoundChips,
      withVuetify({
        props: {
          roundHistory: [chip({ session_id: 's1' })],
          activeSessions: [],
          expandedSessionId: null,
        },
      }),
    )
    await wrapper.findComponent({ name: 'VChip' }).trigger('click')
    expect(wrapper.emitted('toggle-session')).toEqual([['s1']])
  })

  it('still spins a live running chip', () => {
    const wrapper = mount(
      RoundChips,
      withVuetify({
        props: {
          roundHistory: [],
          activeSessions: [live({ status: 'running' })],
          expandedSessionId: null,
        },
      }),
    )
    expect(
      wrapper.findComponent({ name: 'VProgressCircular' }).exists(),
    ).toBe(true)
  })
})

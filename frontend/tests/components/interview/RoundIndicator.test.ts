import { describe, it, expect, afterEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import RoundIndicator from '../../../src/components/interview/RoundIndicator.vue'

let wrappers: VueWrapper[] = []
function mountIndicator(
  current: number | null,
  cap: number | null,
): VueWrapper {
  const wrapper = mount(
    RoundIndicator,
    withVuetify({ props: { current, cap } }),
  )
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  for (const w of wrappers) w.unmount()
  wrappers = []
})

describe('RoundIndicator', () => {
  it('states round 3 of 3 as the final round', () => {
    const wrapper = mountIndicator(3, 3)
    expect(wrapper.find('[data-testid="round-chip"]').text()).toBe(
      'Round 3 of 3',
    )
    expect(wrapper.find('[data-testid="final-round-notice"]').exists()).toBe(
      true,
    )
  })

  it('does not state finality mid-sequence', () => {
    const wrapper = mountIndicator(1, 3)
    expect(wrapper.find('[data-testid="round-chip"]').text()).toBe(
      'Round 1 of 3',
    )
    expect(wrapper.find('[data-testid="final-round-notice"]').exists()).toBe(
      false,
    )
  })

  it('degrades to a single round when not round-capped', () => {
    const wrapper = mountIndicator(null, null)
    expect(wrapper.find('[data-testid="round-chip"]').text()).toBe(
      'Single round',
    )
    expect(wrapper.find('[data-testid="final-round-notice"]').exists()).toBe(
      false,
    )
    expect(wrapper.findComponent({ name: 'PhaseProgress' }).exists()).toBe(
      false,
    )
  })
})

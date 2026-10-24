import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import PhaseProgress from '../../../src/components/common/PhaseProgress.vue'

describe('PhaseProgress', () => {
  it('renders a chunked bar sized to the sequence length', () => {
    const wrapper = mount(
      PhaseProgress,
      withVuetify({ props: { count: 10, ordinal: 3 } }),
    )
    const bar = wrapper.findComponent({ name: 'VProgressLinear' })
    expect(bar.exists()).toBe(true)
    expect(bar.props('chunkCount')).toBe(10)
  })

  it('renders no position bar for a null ordinal', () => {
    const wrapper = mount(
      PhaseProgress,
      withVuetify({ props: { count: 10, ordinal: null } }),
    )
    expect(wrapper.findComponent({ name: 'VProgressLinear' }).exists()).toBe(
      false,
    )
  })
})

import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import StateBar from '../../../src/components/board/StateBar.vue'
import type { CardState } from '../../../src/types/workflows'

function mountBar(stateCounts: Partial<Record<CardState, number>>) {
  return mount(StateBar, withVuetify({ props: { stateCounts } }))
}

describe('StateBar', () => {
  it('renders nothing when the request has no cards', () => {
    const wrapper = mountBar({ ready: 0 })
    expect(wrapper.find('[data-testid="state-bar"]').exists()).toBe(false)
  })

  it('draws one segment per state, sized by its count', () => {
    const wrapper = mountBar({ ready: 2, done: 3 })
    const segments = wrapper.findAll('[data-state]')
    expect(segments.map((s) => s.attributes('data-state'))).toEqual([
      'done',
      'ready',
    ])
    expect(segments[0].attributes('style')).toContain('flex-grow: 3')
    expect(segments[0].attributes('aria-label')).toBe('3 done')
    const bars = wrapper.findAllComponents({ name: 'VProgressLinear' })
    expect(bars.map((b) => b.props('color'))).toEqual(['success', 'info'])
  })

  it('keeps the bar on one row and names every count in a legend', () => {
    const wrapper = mountBar({ ready: 2, done: 1 })
    expect(wrapper.find('[data-testid="state-bar"]').classes()).toContain(
      'flex-nowrap',
    )
    const legend = wrapper.find('[data-testid="state-legend"]').text()
    expect(legend).toContain('1 done')
    expect(legend).toContain('2 ready')
  })
})

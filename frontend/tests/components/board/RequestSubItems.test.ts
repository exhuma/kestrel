import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import RequestSubItems from '../../../src/components/board/RequestSubItems.vue'

describe('RequestSubItems', () => {
  it('renders nothing when there is no own-card activity', () => {
    const wrapper = mount(
      RequestSubItems,
      withVuetify({ props: { stateCounts: {} } }),
    )
    expect(wrapper.findComponent({ name: 'VList' }).exists()).toBe(false)
  })

  it('summarises own cards by state count', () => {
    const wrapper = mount(
      RequestSubItems,
      withVuetify({ props: { stateCounts: { ready: 2, done: 1 } } }),
    )
    expect(wrapper.text()).toContain('2 ready')
    expect(wrapper.text()).toContain('1 done')
  })
})

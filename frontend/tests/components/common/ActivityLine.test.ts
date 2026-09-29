import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import ActivityLine from '../../../src/components/common/ActivityLine.vue'
import type { RequestActivity } from '../../../src/types/workflows'

function mountLine(activity: RequestActivity | null) {
  return mount(ActivityLine, withVuetify({ props: { activity } }))
}

const working: RequestActivity = {
  state: 'working',
  actor: 'screening',
  subject: null,
  detail: null,
  reason: null,
  since: null,
  tool: null,
  tool_calls: null,
}

describe('ActivityLine (feature 033)', () => {
  it('shows a live indicator only while working', () => {
    const busy = mountLine(working)
    expect(busy.text()).toContain('Screening input…')
    expect(busy.findComponent({ name: 'VProgressCircular' }).exists()).toBe(
      true,
    )

    const stalled = mountLine({
      ...working,
      state: 'stalled',
      reason: 'nothing_ready',
    })
    expect(stalled.findComponent({ name: 'VProgressCircular' }).exists()).toBe(
      false,
    )
  })

  it('renders nothing without an activity', () => {
    expect(mountLine(null).find('[data-testid="activity-line"]').exists()).toBe(
      false,
    )
  })
})

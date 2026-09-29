import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import WorkList from '../../../src/components/cockpit/WorkList.vue'
import { boardEvent, workCardSummary } from '../../support/board'

describe('WorkList', () => {
  it('renders nothing for a request without cards', () => {
    const wrapper = mount(
      WorkList,
      withVuetify({ props: { cards: [], events: [] } }),
    )
    expect(wrapper.find('#work').exists()).toBe(false)
  })

  it('names what was cancelled and why, open by default', () => {
    const wrapper = mount(
      WorkList,
      withVuetify({
        props: {
          cards: [
            workCardSummary({
              id: 'c',
              title: 'Draft PRD',
              state: 'cancelled',
            }),
            workCardSummary({ id: 'd', title: 'Screen', state: 'done' }),
          ],
          events: [
            boardEvent({ card_id: 'c', event_type: 'intervention.cancel' }),
          ],
        },
      }),
    )
    const cancelled = wrapper.find('[data-testid="work-group-cancelled"]')
    expect(cancelled.text()).toContain('Cancelled (1)')
    expect(cancelled.text()).toContain('Draft PRD')
    expect(cancelled.find('[data-testid="ended-because"]').text()).toBe(
      'You cancelled it',
    )
    expect(wrapper.find('[data-testid="work-group-done"]').text()).toContain(
      'Done (1)',
    )
  })
})

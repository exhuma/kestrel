import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import WorkList from '../../../src/components/cockpit/WorkList.vue'
import { boardEvent, workCardSummary } from '../../support/board'

describe('WorkList', () => {
  it('says a task waits for its work item to be handed over (#99)', () => {
    const wrapper = mount(
      WorkList,
      withVuetify({
        props: {
          cards: [
            workCardSummary({
              id: 'h',
              title: 'Add the table',
              state: 'waiting_handover',
            }),
          ],
          events: [],
        },
      }),
    )
    const waiting = wrapper.find('[data-testid="work-group-waiting"]')
    expect(waiting.text()).toContain('Add the table')
    expect(waiting.find('[data-testid="state-note"]').text()).toBe(
      'Waiting for hand-over',
    )
  })

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

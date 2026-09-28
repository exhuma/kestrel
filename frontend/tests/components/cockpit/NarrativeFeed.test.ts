import { describe, it, expect } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import NarrativeFeed from '../../../src/components/cockpit/NarrativeFeed.vue'
import { boardEvent } from '../../support/board'
import type { BoardEvent } from '../../../src/types/workflows'

function mountFeed(events: BoardEvent[]) {
  return mount(NarrativeFeed, withVuetify({ props: { events } }))
}

/** Give the feed pane a real scroll geometry. jsdom does no layout, so
 *  scrollHeight/clientHeight are always 0 and scrollTop ignores writes —
 *  all three have to be defined for a scroll behaviour to be testable. */
function withGeometry(
  el: HTMLElement,
  scrollHeight: number,
  clientHeight: number,
  scrollTop: number,
): void {
  Object.defineProperty(el, 'scrollHeight', {
    value: scrollHeight,
    configurable: true,
  })
  Object.defineProperty(el, 'clientHeight', {
    value: clientHeight,
    configurable: true,
  })
  Object.defineProperty(el, 'scrollTop', {
    value: scrollTop,
    writable: true,
    configurable: true,
  })
}

describe('NarrativeFeed ordering and attribution', () => {
  it('renders every event in the order given, oldest first', () => {
    const wrapper = mountFeed([
      boardEvent({ event_type: 'workflow.created', payload: 'one' }),
      boardEvent({ event_type: 'gate.approved', payload: 'two' }),
    ])
    const text = wrapper.text()
    expect(text.indexOf('Request ingested')).toBeLessThan(
      text.indexOf('You approved this gate'),
    )
  })

  it('attributes each row to a persona, naming the neutral case', () => {
    const wrapper = mountFeed([
      boardEvent({ event_type: 'workflow.created', specialist: null }),
      boardEvent({
        event_type: 'card.result_accepted',
        specialist: { id: 'pm', label: 'Product manager' },
      }),
    ])
    expect(wrapper.text()).toContain('System')
    expect(wrapper.text()).toContain('Product manager')
  })

  it('tones the dots by outcome', () => {
    const wrapper = mountFeed([
      boardEvent({ event_type: 'gate.approved' }),
      boardEvent({ event_type: 'card.recovery_escalated' }),
    ])
    const colors = wrapper
      .findAllComponents({ name: 'VTimelineItem' })
      .map((i) => i.props('dotColor'))
    expect(colors).toEqual(['success', 'error'])
  })

  it('says so when there is no history yet', () => {
    expect(mountFeed([]).text()).toContain('Nothing has happened yet')
  })
})

describe('NarrativeFeed live append', () => {
  it('appends new events without a manual refresh', async () => {
    const events: BoardEvent[] = [
      boardEvent({ event_type: 'workflow.created' }),
    ]
    const wrapper = mountFeed(events)
    expect(wrapper.text()).not.toContain('You approved this gate')

    await wrapper.setProps({
      events: [...events, boardEvent({ event_type: 'gate.approved' })],
    })
    expect(wrapper.text()).toContain('You approved this gate')
  })

  it('scrolls to the newest event while the operator is at the live edge', async () => {
    const wrapper = mountFeed([boardEvent({ event_type: 'workflow.created' })])
    const el = wrapper.element as HTMLElement
    withGeometry(el, 500, 500, 0)

    await wrapper.setProps({
      events: [
        boardEvent({ event_type: 'workflow.created' }),
        boardEvent({ event_type: 'gate.approved' }),
      ],
    })
    await flushPromises()
    expect(el.scrollTop).toBe(500)
  })

  it('does not yank a scrolled-back operator to the bottom', async () => {
    const wrapper = mountFeed([boardEvent({ event_type: 'workflow.created' })])
    const el = wrapper.element as HTMLElement
    // Far from the bottom, and the operator has just scrolled there.
    withGeometry(el, 2000, 400, 100)
    await wrapper.trigger('scroll')

    await wrapper.setProps({
      events: [
        boardEvent({ event_type: 'workflow.created' }),
        boardEvent({ event_type: 'gate.approved' }),
      ],
    })
    await flushPromises()
    expect(el.scrollTop).toBe(100)
  })

  it('resumes auto-scroll once the operator returns to the live edge', async () => {
    const wrapper = mountFeed([boardEvent({ event_type: 'workflow.created' })])
    const el = wrapper.element as HTMLElement
    withGeometry(el, 2000, 400, 100)
    await wrapper.trigger('scroll')
    withGeometry(el, 2000, 400, 1600)
    await wrapper.trigger('scroll')

    await wrapper.setProps({
      events: [
        boardEvent({ event_type: 'workflow.created' }),
        boardEvent({ event_type: 'gate.approved' }),
      ],
    })
    await flushPromises()
    expect(el.scrollTop).toBe(2000)
  })
})

describe('NarrativeFeed at scale', () => {
  it('renders every row of a long history rather than silently capping it', () => {
    const events = Array.from({ length: 200 }, (_, i) =>
      boardEvent({ event_type: 'card.result_accepted', payload: `event ${i}` }),
    )
    const wrapper = mountFeed(events)
    expect(wrapper.findAllComponents({ name: 'VTimelineItem' })).toHaveLength(
      200,
    )
    expect(wrapper.text()).toContain('event 199')
  })
})

describe('NarrativeFeed is monitoring only', () => {
  it('offers no way to answer anything from the feed (FR-017)', () => {
    const wrapper = mountFeed([
      boardEvent({ event_type: 'gate.approved' }),
      boardEvent({ event_type: 'card.result_accepted' }),
    ])
    expect(wrapper.findAllComponents({ name: 'VBtn' })).toHaveLength(0)
    expect(wrapper.findAllComponents({ name: 'VTextarea' })).toHaveLength(0)
    expect(wrapper.findAllComponents({ name: 'VTextField' })).toHaveLength(0)
  })
})

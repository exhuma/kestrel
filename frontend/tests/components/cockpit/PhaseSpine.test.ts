import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import PhaseSpine from '../../../src/components/cockpit/PhaseSpine.vue'
import { PHASE_ORDER } from '../../../src/lib/stages'
import type { PhaseStatus } from '../../../src/types/workflows'

function mountSpine(phase: string, phases: PhaseStatus[] = []) {
  return mount(PhaseSpine, withVuetify({ props: { phase, phases } }))
}

function items(wrapper: ReturnType<typeof mountSpine>) {
  return wrapper.findAllComponents({ name: 'VTimelineItem' })
}

const FINISHED: PhaseStatus[] = PHASE_ORDER.map((name, i) => ({
  name,
  status: i === 6 ? 'skipped' : 'done',
}))

describe('PhaseSpine sequence', () => {
  it('renders all ten phases in order', () => {
    const wrapper = mountSpine('PRD')
    expect(items(wrapper)).toHaveLength(10)
    const text = wrapper.text()
    for (const phase of PHASE_ORDER) expect(text).toContain(phase)
  })
})

describe('PhaseSpine step status (feature 034)', () => {
  it('marks every step of a finished request, none left blank', () => {
    const wrapper = mountSpine('done', FINISHED)
    const icons = items(wrapper).map((i) => i.props('icon'))
    expect(icons.filter((i) => i === '$checkCircle')).toHaveLength(9)
    expect(icons[6]).toBe('$minusCircleOutline')
    expect(wrapper.text()).toContain('Skipped')
    expect(wrapper.text()).not.toContain('Not reached')
  })

  it('tells each status apart by icon and word, not colour alone', () => {
    const phases: PhaseStatus[] = [
      { name: 'Intake', status: 'done' },
      { name: 'Understanding', status: 'problem' },
      { name: 'CAB-1 - strategic fit', status: 'waiting' },
      { name: 'Pre-assessment', status: 'active' },
    ]
    const wrapper = mountSpine('Pre-assessment', phases)
    const icons = items(wrapper).map((i) => i.props('icon'))
    expect(icons.slice(0, 5)).toEqual([
      '$checkCircle',
      '$alertCircle',
      '$accountClock',
      '$progressClock',
      '$circleOutline',
    ])
    for (const word of ['Done', 'Problem', 'Waiting for you', 'In progress'])
      expect(wrapper.text()).toContain(word)
  })

  it('reads an unreported step as not reached', () => {
    const wrapper = mountSpine('Intake')
    const colors = items(wrapper).map((i) => i.props('dotColor'))
    expect(colors.every((c) => c === undefined)).toBe(true)
  })
})

describe('PhaseSpine gate distinction', () => {
  it('marks the three gate phases beside their label', () => {
    const wrapper = mountSpine('PRD')
    const marked = items(wrapper).map((i) =>
      i.find('[data-testid="gate-mark"]').exists(),
    )
    // CAB-1 (3rd), PRD sign-off (6th) and CAB-2 (8th) are the gates.
    expect(marked.filter(Boolean)).toHaveLength(3)
    expect([marked[2], marked[5], marked[7]]).toEqual([true, true, true])
  })
})

describe('PhaseSpine unrecognised phase', () => {
  it('renders the label verbatim with no position marker', () => {
    const wrapper = mountSpine('Rethinking everything')
    expect(wrapper.text()).toContain('Rethinking everything')
    const statuses = items(wrapper).map((i) => i.attributes('data-status'))
    expect(statuses.every((st) => st === 'upcoming')).toBe(true)
  })

  it('says the phase is outside the standard sequence rather than guessing', () => {
    const wrapper = mountSpine('Rethinking everything')
    expect(wrapper.text()).toContain('not part of the standard sequence')
  })

  it('does not show that notice for the synthetic terminal phase', () => {
    const wrapper = mountSpine('done')
    expect(wrapper.text()).not.toContain('not part of the standard sequence')
  })
})

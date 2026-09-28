import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import PhaseSpine from '../../../src/components/cockpit/PhaseSpine.vue'
import { PHASE_ORDER } from '../../../src/lib/stages'

function mountSpine(phase: string) {
  return mount(PhaseSpine, withVuetify({ props: { phase } }))
}

function items(wrapper: ReturnType<typeof mountSpine>) {
  return wrapper.findAllComponents({ name: 'VTimelineItem' })
}

describe('PhaseSpine sequence', () => {
  it('renders all ten phases in order', () => {
    const wrapper = mountSpine('PRD')
    expect(items(wrapper)).toHaveLength(10)
    const text = wrapper.text()
    for (const phase of PHASE_ORDER) expect(text).toContain(phase)
  })
})

describe('PhaseSpine current-phase highlighting', () => {
  // "PRD sign-off" is the 6th of ten: five passed, one current, four not
  // yet reached.
  it('marks five phases passed and four not yet reached for PRD sign-off', () => {
    const wrapper = mountSpine('PRD sign-off')
    const colors = items(wrapper).map((i) => i.props('dotColor'))
    expect(colors.filter((c) => c === 'success')).toHaveLength(5)
    expect(colors.filter((c) => c === 'primary')).toHaveLength(1)
    expect(colors.filter((c) => c === undefined)).toHaveLength(4)
  })

  it('marks the current phase with the primary colour at its own position', () => {
    const wrapper = mountSpine('PRD sign-off')
    expect(items(wrapper)[5].props('dotColor')).toBe('primary')
    expect(wrapper.text()).toContain('Current phase')
  })

  it('claims nothing passed at the first phase', () => {
    const wrapper = mountSpine('Intake')
    const colors = items(wrapper).map((i) => i.props('dotColor'))
    expect(colors.filter((c) => c === 'success')).toHaveLength(0)
    expect(colors[0]).toBe('primary')
  })
})

describe('PhaseSpine gate distinction', () => {
  it('gives the three gate phases a distinct icon and work phases none', () => {
    const wrapper = mountSpine('PRD')
    const icons = items(wrapper).map((i) => i.props('icon'))
    expect(icons.filter((i) => i === '$shieldAlert')).toHaveLength(3)
    // CAB-1 (3rd), PRD sign-off (6th) and CAB-2 (8th) are the gates.
    expect([icons[2], icons[5], icons[7]]).toEqual([
      '$shieldAlert',
      '$shieldAlert',
      '$shieldAlert',
    ])
    expect(icons[0]).toBeUndefined()
  })
})

describe('PhaseSpine unrecognised phase', () => {
  it('renders the label verbatim with no position marker', () => {
    const wrapper = mountSpine('Rethinking everything')
    expect(wrapper.text()).toContain('Rethinking everything')
    const colors = items(wrapper).map((i) => i.props('dotColor'))
    expect(colors.every((c) => c === undefined)).toBe(true)
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

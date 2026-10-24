import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import { workCardSummary } from '../../support/board'
import type { WorkCardSummary } from '../../../src/types/workflows'

const mockApplyIntervention = vi.fn()
vi.mock('../../../src/composables/useBoard', () => ({
  useBoard: () => ({ applyIntervention: mockApplyIntervention }),
}))

import ManualTaskList from '../../../src/components/cockpit/ManualTaskList.vue'

let wrappers: VueWrapper[] = []

function manualTask(overrides: Partial<WorkCardSummary> = {}) {
  return workCardSummary({
    id: 'man-1',
    title: 'Request the vendor API key',
    card_type: 'manual_task',
    state: 'awaiting_human',
    allowed_actions: ['cancel', 'complete_manual_task'],
    latest_artifact: { id: 'art-1', label: 'task_spec', revision: 1 },
    ...overrides,
  })
}

function mountList(cards: WorkCardSummary[]): VueWrapper {
  const wrapper = mount(ManualTaskList, withVuetify({ props: { cards } }))
  wrappers.push(wrapper)
  return wrapper
}

function button(wrapper: VueWrapper, label: string) {
  return wrapper
    .findAllComponents({ name: 'VBtn' })
    .find((b) => b.text() === label)
}

beforeEach(() => {
  mockApplyIntervention.mockReset()
})

afterEach(() => {
  wrappers.forEach((w) => w.unmount())
  wrappers = []
})

describe('ManualTaskList', () => {
  it('lists only the manual tasks, with their state', () => {
    const wrapper = mountList([
      manualTask(),
      workCardSummary({ id: 'impl', title: 'Build the client' }),
    ])
    expect(wrapper.text()).toContain('Request the vendor API key')
    expect(wrapper.text()).toContain('To do')
    expect(wrapper.text()).not.toContain('Build the client')
  })

  it('marks a task done through the intervention endpoint', async () => {
    const wrapper = mountList([manualTask()])

    await button(wrapper, 'Mark done')?.trigger('click')
    await flushPromises()

    expect(mockApplyIntervention).toHaveBeenCalledWith(
      'man-1',
      'complete_manual_task',
    )
  })

  it('offers no "Mark done" when the backend does not allow it', () => {
    const wrapper = mountList([
      manualTask({ state: 'waiting_dependency', allowed_actions: ['cancel'] }),
    ])
    expect(button(wrapper, 'Mark done')).toBeUndefined()
    expect(wrapper.text()).toContain('Waiting on earlier work')
  })

  it('offers the approved task text to read', () => {
    const wrapper = mountList([manualTask()])
    expect(button(wrapper, 'Read task')).toBeDefined()
  })

  it('renders nothing for a request without manual tasks', () => {
    const wrapper = mountList([workCardSummary()])
    expect(wrapper.text()).toBe('')
  })
})

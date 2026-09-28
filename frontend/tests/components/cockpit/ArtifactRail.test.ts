import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import ArtifactRail from '../../../src/components/cockpit/ArtifactRail.vue'
import { workCardSummary } from '../../support/board'
import type { WorkCardSummary } from '../../../src/types/workflows'

const PIPELINE_ORDER = [
  'Original request',
  'Understanding check',
  'CAB-1 decision',
  'Interview rounds',
  'PRD',
  'Technical analysis',
  'Executive summary',
  'Pull request',
]

let wrappers: VueWrapper[] = []

function mountRail(cards: WorkCardSummary[] = []): VueWrapper {
  const wrapper = mount(ArtifactRail, withVuetify({ props: { cards } }))
  wrappers.push(wrapper)
  return wrapper
}

function rowTitles(wrapper: VueWrapper): string[] {
  return wrapper
    .findAllComponents({ name: 'VListItem' })
    .map((i) => i.props('title') as string)
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ content: 'body', trust: 'agent_output' }),
          {
            status: 200,
          },
        ),
    ),
  )
})
afterEach(() => {
  for (const w of wrappers) w.unmount()
  wrappers = []
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('ArtifactRail durable set', () => {
  it('renders the full durable set in pipeline order', () => {
    expect(rowTitles(mountRail())).toEqual(PIPELINE_ORDER)
  })

  it('shows unproduced artifacts as unavailable rather than omitting them', () => {
    const wrapper = mountRail([
      workCardSummary({ card_type: 'prd', state: 'done' }),
    ])
    expect(rowTitles(wrapper)).toEqual(PIPELINE_ORDER)
    expect(wrapper.text()).toContain('Not yet produced')
  })

  it('states each entry with its own state', () => {
    const wrapper = mountRail([
      workCardSummary({ card_type: 'understanding_gate', state: 'done' }),
      workCardSummary({
        card_type: 'refinement_gate',
        state: 'awaiting_human',
      }),
    ])
    expect(wrapper.text()).toContain('Produced')
    expect(wrapper.text()).toContain('Awaiting your decision')
  })

  it('disables an entry with nothing behind it to open', () => {
    const wrapper = mountRail()
    const rows = wrapper.findAllComponents({ name: 'VListItem' })
    expect(rows.every((r) => r.props('disabled') === true)).toBe(true)
  })

  it('enables an entry that has content', () => {
    const wrapper = mountRail([
      workCardSummary({
        card_type: 'prd',
        state: 'done',
        latest_artifact: { id: 'art-1', label: 'draft', revision: 1 },
      }),
    ])
    const prd = wrapper
      .findAllComponents({ name: 'VListItem' })
      .find((r) => r.props('title') === 'PRD')
    expect(prd?.props('disabled')).toBe(false)
  })
})

describe('ArtifactRail opening an artifact', () => {
  it('opens the artifact content when an available entry is chosen', async () => {
    const wrapper = mountRail([
      workCardSummary({
        card_type: 'prd',
        state: 'done',
        latest_artifact: { id: 'art-1', label: 'draft', revision: 1 },
      }),
    ])
    const prd = wrapper
      .findAllComponents({ name: 'VListItem' })
      .find((r) => r.props('title') === 'PRD')
    await prd?.trigger('click')
    await flushPromises()

    const dialog = wrapper.findComponent({ name: 'ArtifactDialog' })
    expect(dialog.props('artifactId')).toBe('art-1')
    expect(dialog.props('label')).toBe('PRD')
    expect(document.body.textContent).toContain('body')
  })

  it('opens nothing for an unavailable entry', async () => {
    const wrapper = mountRail()
    await wrapper.findAllComponents({ name: 'VListItem' })[0].trigger('click')
    expect(
      wrapper.findComponent({ name: 'ArtifactDialog' }).props('artifactId'),
    ).toBeNull()
  })
})

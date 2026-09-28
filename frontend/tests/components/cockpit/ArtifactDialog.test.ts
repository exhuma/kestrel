import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import ArtifactDialog from '../../../src/components/cockpit/ArtifactDialog.vue'

// `v-dialog` teleports its content to `document.body`, so it is outside the
// wrapper's own element. Component lookups still traverse the component
// tree, but text assertions have to read the document.
function shownText(): string {
  return document.body.textContent ?? ''
}
function shownHtml(): string {
  return document.body.innerHTML
}

let wrappers: VueWrapper[] = []

function mountDialog(artifactId: string | null = 'art-1'): VueWrapper {
  const wrapper = mount(
    ArtifactDialog,
    withVuetify({ props: { artifactId, label: 'PRD' } }),
  )
  wrappers.push(wrapper)
  return wrapper
}

function stubContent(content: string, trust: string): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ content, trust }), { status: 200 }),
    ),
  )
}

async function openWith(content: string, trust = 'agent_output') {
  stubContent(content, trust)
  const wrapper = mountDialog()
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('not found', { status: 404 })),
  )
})
afterEach(() => {
  for (const w of wrappers) w.unmount()
  wrappers = []
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('ArtifactDialog content safety', () => {
  it('renders markup in the content as literal text, never as markup', async () => {
    await openWith('<em>pwned</em>')
    expect(shownText()).toContain('<em>pwned</em>')
    expect(shownHtml()).not.toContain('<em>pwned</em>')
  })

  it('shows the artifact content', async () => {
    await openWith('The product requirements.')
    expect(shownText()).toContain('The product requirements.')
  })
})

describe('ArtifactDialog trust', () => {
  it('always displays the trust level', async () => {
    const wrapper = await openWith('body', 'agent_output')
    expect(wrapper.findComponent({ name: 'VChip' }).text()).toBe('agent_output')
  })

  it('distinguishes operator-approved from agent output by colour', async () => {
    const approved = await openWith('body', 'operator_approved')
    expect(approved.findComponent({ name: 'VChip' }).props('color')).toBe(
      'success',
    )
  })

  it('marks unapproved agent output as such', async () => {
    const agent = await openWith('body', 'agent_output')
    expect(agent.findComponent({ name: 'VChip' }).props('color')).toBe(
      'warning',
    )
  })
})

describe('ArtifactDialog states', () => {
  it('says so plainly when the artifact cannot be read', async () => {
    mountDialog()
    await flushPromises()
    expect(shownText()).toContain('Could not load this artifact')
  })

  it('stays closed when no artifact is selected', () => {
    const wrapper = mountDialog(null)
    expect(wrapper.findComponent({ name: 'VDialog' }).props('modelValue')).toBe(
      false,
    )
  })

  it('emits close when dismissed', async () => {
    const wrapper = await openWith('body')
    const close = wrapper
      .findAllComponents({ name: 'VBtn' })
      .find((b) => b.text() === 'Close')
    await close?.trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})

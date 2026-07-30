import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import MockupPanel from '../../src/components/MockupPanel.vue'
import type { Mockup } from '../../src/types/questionnaire'

const mockups: Mockup[] = [
  {
    name: 'login-01.png',
    url: '/api/workflows/wf-1/screenshots/refine/login-01.png',
    explanation: 'the login screen',
  },
]

function panel(feedback: Record<string, string> = {}) {
  return mount(MockupPanel, withVuetify({ props: { mockups, feedback } }))
}

beforeEach(() => {
  // jsdom lacks visualViewport, which Vuetify's dialog overlay reads.
  vi.stubGlobal('visualViewport', {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    width: 1024,
    height: 768,
    offsetLeft: 0,
    offsetTop: 0,
    scale: 1,
  })
})

describe('MockupPanel', () => {
  it('renders a thumbnail (absolute src) and the explanation', () => {
    const wrapper = panel()
    const img = wrapper.findComponent({ name: 'VImg' })
    expect(String(img.props('src'))).toBe(
      'http://localhost:8000/api/workflows/wf-1/screenshots/refine/login-01.png',
    )
    expect(wrapper.text()).toContain('the login screen')
  })

  it('emits update:feedback with the mockup name on input', async () => {
    const wrapper = panel()
    const textarea = wrapper
      .find('[data-testid="mockup-feedback"]')
      .find('textarea')
    await textarea.setValue('move the button')
    const events = wrapper.emitted('update:feedback')
    expect(events).toBeTruthy()
    expect(events!.at(-1)).toEqual(['login-01.png', 'move the button'])
  })

  it('opens the lightbox dialog when the thumbnail is clicked', async () => {
    const wrapper = panel()
    const dialog = wrapper.findComponent({ name: 'VDialog' })
    expect(dialog.props('modelValue')).toBe(false)
    await wrapper.findComponent({ name: 'VImg' }).trigger('click')
    expect(dialog.props('modelValue')).toBe(true)
  })
})

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'

const mockRequestChanges = vi.fn()
vi.mock('../../../src/composables/useBoard', () => ({
  useBoard: () => ({ requestChanges: mockRequestChanges }),
}))

import RequestChanges from '../../../src/components/cockpit/RequestChanges.vue'

let wrapper: VueWrapper

function buttons() {
  return wrapper
    .findAllComponents({ name: 'VBtn' })
    .filter((b) => b.text() === 'Request changes')
}

async function openDialog(): Promise<void> {
  await buttons()[0].trigger('click')
  await flushPromises()
}

async function write(text: string): Promise<void> {
  wrapper
    .findComponent({ name: 'VTextarea' })
    .vm.$emit('update:modelValue', text)
  await flushPromises()
}

async function send(): Promise<void> {
  await buttons().at(-1)?.trigger('click')
  await flushPromises()
}

beforeEach(() => {
  mockRequestChanges.mockReset()
  mockRequestChanges.mockResolvedValue(null)
  wrapper = mount(RequestChanges, withVuetify({ attachTo: document.body }))
})

afterEach(() => {
  wrapper.unmount()
  document.body.innerHTML = ''
})

describe('RequestChanges', () => {
  it('sends what the reviewer wrote', async () => {
    await openDialog()
    await write('  Rename the button  ')
    await send()

    expect(mockRequestChanges).toHaveBeenCalledWith('Rename the button')
  })

  it('sends nothing without feedback', async () => {
    await openDialog()
    await write('   ')
    await send()

    expect(mockRequestChanges).not.toHaveBeenCalled()
  })

  it('closes once the request went through', async () => {
    await openDialog()
    await write('Rename the button')
    await send()

    expect(wrapper.findComponent({ name: 'VDialog' }).props('modelValue')).toBe(
      false,
    )
  })

  it('keeps the text and says why when refused', async () => {
    mockRequestChanges.mockResolvedValue('the change request is merged')
    await openDialog()
    await write('Rename the button')
    await send()

    expect(wrapper.findComponent({ name: 'VDialog' }).props('modelValue')).toBe(
      true,
    )
    expect(
      wrapper.findComponent({ name: 'VTextarea' }).props('modelValue'),
    ).toBe('Rename the button')
    expect(document.body.textContent).toContain('the change request is merged')
  })
})

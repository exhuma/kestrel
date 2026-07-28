import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import ScreenshotGallery from '../../src/components/ScreenshotGallery.vue'
import type { Screenshot } from '../../src/types/workflows'

const shots: Screenshot[] = [
  {
    name: 'a.png',
    stage: 'verify',
    url: '/api/workflows/wf-1/screenshots/verify/a.png',
  },
  {
    name: 'm.png',
    stage: 'refine',
    url: '/api/workflows/wf-1/screenshots/refine/m.png',
  },
]

function stubFetch(data: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, status: 200, json: async () => data })),
  )
}

function galleryFor(stage: 'refine' | 'verify') {
  return mount(
    ScreenshotGallery,
    withVuetify({ props: { workflowId: 'wf-1', stage } }),
  )
}

function imageSrcs(wrapper: ReturnType<typeof galleryFor>): string[] {
  return wrapper
    .findAllComponents({ name: 'VImg' })
    .map((c) => String(c.props('src')))
}

beforeEach(() => {
  vi.restoreAllMocks()
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

describe('ScreenshotGallery', () => {
  it('renders only the given stage as an absolute-src thumbnail', async () => {
    stubFetch(shots)
    const wrapper = galleryFor('verify')
    await flushPromises()
    const srcs = imageSrcs(wrapper)
    expect(srcs).toContain(
      'http://localhost:8000/api/workflows/wf-1/screenshots/verify/a.png',
    )
    // The refine shot is filtered out of a verify gallery.
    expect(srcs.some((s) => s.includes('refine'))).toBe(false)
  })

  it('renders nothing when the stage has no shots', async () => {
    stubFetch([])
    const wrapper = galleryFor('refine')
    await flushPromises()
    expect(wrapper.findAllComponents({ name: 'VImg' })).toHaveLength(0)
  })

  it('opens the lightbox dialog when a thumbnail is clicked', async () => {
    stubFetch(shots)
    const wrapper = galleryFor('verify')
    await flushPromises()
    const dialog = wrapper.findComponent({ name: 'VDialog' })
    expect(dialog.props('modelValue')).toBe(false)
    await wrapper.findComponent({ name: 'VImg' }).trigger('click')
    expect(dialog.props('modelValue')).toBe(true)
  })
})

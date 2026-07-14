import { describe, it, expect, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import GithubLink from '../../src/components/GithubLink.vue'
import { withVuetify } from '../support/vuetify'

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('GithubLink', () => {
  it('renders a safe external link when the repo URL is set', () => {
    vi.stubEnv('VITE_GITHUB_REPO_URL', 'https://github.com/exhuma/kestrel')
    const wrapper = mount(GithubLink, withVuetify())
    // The Vuetify v-btn renders an <a> when given an href.
    const a = wrapper.find('a')
    expect(a.exists()).toBe(true)
    expect(a.attributes('href')).toBe('https://github.com/exhuma/kestrel')
    expect(a.attributes('target')).toBe('_blank')
    expect(a.attributes('rel')).toBe('noopener noreferrer')
    expect(a.attributes('aria-label')).toBe('Source code')
  })

  it('renders nothing when the repo URL is unset', () => {
    vi.stubEnv('VITE_GITHUB_REPO_URL', undefined as unknown as string)
    const wrapper = mount(GithubLink, withVuetify())
    expect(wrapper.find('a').exists()).toBe(false)
  })

  it('renders nothing when the repo URL is blank', () => {
    vi.stubEnv('VITE_GITHUB_REPO_URL', '   ')
    const wrapper = mount(GithubLink, withVuetify())
    expect(wrapper.find('a').exists()).toBe(false)
  })
})

import { describe, it, expect, afterEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import QuestionField from '../../../src/components/interview/QuestionField.vue'
import type { QuestionAnswer } from '../../../src/types/interview'

const question = { id: 'g1:0', prompt: 'Which auth mechanism?' }

let wrappers: VueWrapper[] = []
function mountField(answer: QuestionAnswer | undefined): VueWrapper {
  const wrapper = mount(
    QuestionField,
    withVuetify({ props: { question, answer } }),
  )
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  for (const w of wrappers) w.unmount()
  wrappers = []
})

describe('QuestionField answer states', () => {
  it('reaches answered by typing text', async () => {
    const wrapper = mountField(undefined)
    await wrapper
      .find('[data-testid="answer-text"] textarea')
      .setValue('OIDC with PKCE')
    const emitted = wrapper.emitted('update:answer')
    expect(emitted?.at(-1)?.[0]).toEqual({
      state: 'answered',
      text: 'OIDC with PKCE',
    })
  })

  it('reaches unknown via its checkbox, carrying no text', async () => {
    const wrapper = mountField(undefined)
    await wrapper.find('[data-testid="toggle-unknown"] input').setValue(true)
    expect(wrapper.emitted('update:answer')?.at(-1)?.[0]).toEqual({
      state: 'unknown',
      text: '',
    })
  })

  it('reaches not-relevant via its checkbox, carrying no text', async () => {
    const wrapper = mountField(undefined)
    await wrapper
      .find('[data-testid="toggle-not-relevant"] input')
      .setValue(true)
    expect(wrapper.emitted('update:answer')?.at(-1)?.[0]).toEqual({
      state: 'not-relevant',
      text: '',
    })
  })

  it('treats whitespace-only text as unanswered, not answered', async () => {
    const wrapper = mountField(undefined)
    await wrapper.find('[data-testid="answer-text"] textarea').setValue('   ')
    expect(wrapper.emitted('update:answer')?.at(-1)?.[0]).toEqual({
      state: 'unanswered',
      text: '   ',
    })
  })

  it('hides the textarea once unknown or not-relevant is chosen', () => {
    const unknown = mountField({ state: 'unknown', text: '' })
    expect(unknown.find('[data-testid="answer-text"]').exists()).toBe(false)

    const notRelevant = mountField({ state: 'not-relevant', text: '' })
    expect(notRelevant.find('[data-testid="answer-text"]').exists()).toBe(false)
  })

  it('neither escape hatch is ever reachable as an empty answered state', async () => {
    const wrapper = mountField({ state: 'unknown', text: '' })
    for (const call of wrapper.emitted('update:answer') ?? []) {
      const answer = call[0] as QuestionAnswer
      if (answer.state === 'answered') expect(answer.text.trim()).not.toBe('')
    }
  })
})

import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import QuestionField from '../../../src/components/interview/QuestionField.vue'
import type {
  InterviewQuestion,
  QuestionAnswer,
} from '../../../src/types/interview'

function mountField(question: InterviewQuestion, answer?: QuestionAnswer) {
  return mount(QuestionField, withVuetify({ props: { question, answer } }))
}

const single: InterviewQuestion = {
  id: 'q1',
  prompt: 'Who uses it?',
  options: ['Finance', 'Sales'],
  multiple: false,
}

describe('QuestionField choices (feature 034)', () => {
  it('answers a single-choice question with one pick', async () => {
    const wrapper = mountField(single)

    const radios = wrapper.findAllComponents({ name: 'VRadio' })
    expect(radios.map((r) => r.props('label'))).toEqual(['Finance', 'Sales'])
    await wrapper
      .findComponent({ name: 'VRadioGroup' })
      .vm.$emit('update:modelValue', 'Sales')

    expect(wrapper.emitted('update:answer')![0][0]).toEqual({
      state: 'answered',
      text: '',
      choices: ['Sales'],
    })
  })

  it('lets several options be picked when the question allows it', async () => {
    const wrapper = mountField(
      { ...single, multiple: true },
      {
        state: 'answered',
        text: '',
        choices: ['Finance'],
      },
    )

    const boxes = wrapper.findAllComponents({ name: 'VCheckbox' })
    await boxes[1].vm.$emit('update:modelValue', true)

    expect(wrapper.emitted('update:answer')![0][0]).toMatchObject({
      state: 'answered',
      choices: ['Finance', 'Sales'],
    })
  })

  it('keeps a comment field, and an open question stays free text', () => {
    const choice = mountField(single)
    expect(choice.findComponent({ name: 'VTextarea' }).props('label')).toBe(
      'Comment (optional)',
    )

    const open = mountField({ id: 'q2', prompt: 'Anything else?' })
    expect(open.find('[data-testid="answer-choices"]').exists()).toBe(false)
    expect(open.find('[data-testid="answer-text"]').exists()).toBe(true)
  })
})

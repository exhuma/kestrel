import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import QuestionnaireForm from '../../src/components/QuestionnaireForm.vue'
import type { Question, Questionnaire } from '../../src/types/questionnaire'

function q(partial: Partial<Question> & { id: string }): Question {
  return {
    prompt: '', why: '', type: 'free_text', required: true, options: [],
    audience: '', waiver_label: 'Unknown / N/A', ...partial,
  }
}

function questionnaire(...questions: Question[]): Questionnaire {
  return { questions, profiles: [] }
}

function blockFor(wrapper: ReturnType<typeof mount>, id: string) {
  return wrapper
    .findAll('.qform__q')
    .find((b) => b.attributes('aria-labelledby') === `qp-${id}`)
}
function textareaFor(wrapper: ReturnType<typeof mount>, id: string) {
  return blockFor(wrapper, id)!.find('textarea.field')
}

describe('QuestionnaireForm', () => {
  it('keeps an in-progress answer across a structurally-equal but new-reference prop update at the same round', async () => {
    const wrapper = mount(QuestionnaireForm, {
      props: {
        questionnaire: questionnaire(q({ id: 'q1', prompt: 'Which auth?' })),
        draftAnswers: {},
        round: 1,
      },
    })
    await textareaFor(wrapper, 'q1').setValue('use OIDC')
    expect(textareaFor(wrapper, 'q1').element.value).toBe('use OIDC')

    // A fresh SSE frame at the same round: new object references, same
    // content — this must NOT reset the form.
    await wrapper.setProps({
      questionnaire: questionnaire(q({ id: 'q1', prompt: 'Which auth?' })),
      draftAnswers: {},
      round: 1,
    })

    expect(textareaFor(wrapper, 'q1').element.value).toBe('use OIDC')
  })

  it('a custom correction satisfies submit and emits a {custom} answer', async () => {
    const wrapper = mount(QuestionnaireForm, {
      props: {
        questionnaire: questionnaire(q({
          id: 'q1', prompt: 'Which auth?', type: 'single_select',
          options: [{ value: 'oidc', label: 'OIDC' }],
        })),
        draftAnswers: {},
        round: 1,
      },
    })
    // A required, unanswered question keeps submit disabled.
    expect(
      wrapper.find('button[type="submit"]').attributes('disabled'),
    ).toBeDefined()

    const block = blockFor(wrapper, 'q1')!
    await block.find('.qform__toggle--custom input').setValue(true)
    await block.find('.qform__custom textarea').setValue('It is a CLI, not web')

    expect(
      wrapper.find('button[type="submit"]').attributes('disabled'),
    ).toBeUndefined()
    await wrapper.find('form').trigger('submit')
    const submitted = wrapper.emitted('submit')!.at(-1)![0] as Record<
      string, unknown
    >
    expect(submitted.q1).toEqual({ custom: 'It is a CLI, not web' })
  })

  it('wraps a selection plus additional info into {value, note}, and collapses when cleared', async () => {
    const wrapper = mount(QuestionnaireForm, {
      props: {
        questionnaire: questionnaire(q({
          id: 'q1', prompt: 'Which auth?', type: 'single_select',
          options: [{ value: 'oidc', label: 'OIDC' }],
        })),
        draftAnswers: {},
        round: 1,
      },
    })
    const block = blockFor(wrapper, 'q1')!
    await block.find('input[type="radio"]').setValue()
    const note = block.find('.qform__note')
    await note.setValue('SSO only')

    await wrapper.find('form').trigger('submit')
    let submitted = wrapper.emitted('submit')!.at(-1)![0] as Record<
      string, unknown
    >
    expect(submitted.q1).toEqual({ value: 'oidc', note: 'SSO only' })

    // Clearing the note collapses back to the plain selected value.
    await note.setValue('')
    await wrapper.find('form').trigger('submit')
    submitted = wrapper.emitted('submit')!.at(-1)![0] as Record<string, unknown>
    expect(submitted.q1).toBe('oidc')
  })

  it('on a genuine round change, keeps answers for surviving question ids and drops the rest', async () => {
    const wrapper = mount(QuestionnaireForm, {
      props: {
        questionnaire: questionnaire(
          q({ id: 'q1', prompt: 'Which auth?' }),
          q({ id: 'q2', prompt: 'Which region?' }),
        ),
        draftAnswers: {},
        round: 1,
      },
    })
    await textareaFor(wrapper, 'q1').setValue('use OIDC')
    await textareaFor(wrapper, 'q2').setValue('eu-west')

    // Round genuinely advances; q2 is dropped from the new questionnaire.
    await wrapper.setProps({
      questionnaire: questionnaire(q({ id: 'q1', prompt: 'Which auth?' })),
      draftAnswers: {},
      round: 2,
    })

    expect(textareaFor(wrapper, 'q1').element.value).toBe('use OIDC')
    expect(blockFor(wrapper, 'q2')).toBeUndefined()
  })

  it('shows a soft (retrying) notice distinct from a hard one', () => {
    const wrapper = mount(QuestionnaireForm, {
      props: {
        questionnaire: {
          questions: [q({ id: 'q1', prompt: 'Which auth?' })],
          profiles: [],
          issues: [
            { profile: 'infosec', label: 'InfoSec',
              reason: 'timed out after 120s', severity: 'soft' },
            { profile: 'perf', label: 'Perf',
              reason: 'crashed', severity: 'hard' },
          ],
        },
        draftAnswers: {},
        round: 1,
      },
    })
    const soft = wrapper.find('.qform__issues--soft')
    const hard = wrapper.find('.qform__issues--hard')
    expect(soft.exists()).toBe(true)
    expect(soft.text()).toContain('will be retried when you submit')
    expect(soft.text()).toContain('InfoSec')
    expect(hard.exists()).toBe(true)
    expect(hard.text()).toContain('failed after 3 retries')
    expect(hard.text()).toContain('Perf')
  })

  it('allows submitting an incomplete questionnaire when allowIncomplete is set', async () => {
    const wrapper = mount(QuestionnaireForm, {
      props: {
        questionnaire: questionnaire(
          q({ id: 'q1', prompt: 'Which auth?', required: true }),
        ),
        draftAnswers: {},
        round: 1,
        allowIncomplete: true,
      },
    })
    const submit = wrapper.find('button[type="submit"]')
    expect(submit.attributes('disabled')).toBeUndefined()
    expect(submit.text()).toContain('Submit incomplete')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('submit')).toBeTruthy()
  })

  it('keeps submit disabled when incomplete without allowIncomplete', () => {
    const wrapper = mount(QuestionnaireForm, {
      props: {
        questionnaire: questionnaire(
          q({ id: 'q1', prompt: 'Which auth?', required: true }),
        ),
        draftAnswers: {},
        round: 1,
      },
    })
    expect(
      wrapper.find('button[type="submit"]').attributes('disabled'),
    ).toBeDefined()
  })

  it('renders no failure notice when there are no issues', () => {
    const wrapper = mount(QuestionnaireForm, {
      props: {
        questionnaire: questionnaire(q({ id: 'q1', prompt: 'Which auth?' })),
        draftAnswers: {},
        round: 1,
      },
    })
    expect(wrapper.find('.qform__issues').exists()).toBe(false)
  })
})

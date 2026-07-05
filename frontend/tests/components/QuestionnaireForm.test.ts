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
})

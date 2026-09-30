import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import PersonaQuestionGroup from '../../../src/components/interview/PersonaQuestionGroup.vue'
import type { InterviewCard } from '../../../src/types/interview'

function card(persona: string, personaLabel: string): InterviewCard {
  return {
    cardId: 'g1',
    persona,
    personaLabel,
    questions: [{ id: 'g1:0', prompt: 'Where is the data stored?' }],
    round: null,
    cap: null,
  }
}

function mountGroup(c: InterviewCard) {
  return mount(
    PersonaQuestionGroup,
    withVuetify({ props: { card: c, answers: {} } }),
  )
}

describe('PersonaQuestionGroup (features 038, 039)', () => {
  it("names the profile and tints the form in its specialist's colour", () => {
    const wrapper = mountGroup(card('dba', 'Database Specialist'))
    const form = wrapper.find('[data-specialist="dba"]')
    expect(form.text()).toContain('Database Specialist')
    expect(form.classes()).toContain('persona-group--tinted')
    expect(form.attributes('style')).toContain(
      '--specialist: var(--v-theme-specialist-dba)',
    )
  })

  it('leaves a specialist outside the palette neutral', () => {
    const wrapper = mountGroup(card('lawyer', 'Legal'))
    const form = wrapper.find('[data-specialist="lawyer"]')
    expect(form.classes()).not.toContain('persona-group--tinted')
    expect(form.text()).toContain('Legal')
  })
})

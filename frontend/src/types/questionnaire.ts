export type QuestionType =
  | 'single_select'
  | 'multi_select'
  | 'boolean'
  | 'free_text'

export interface QuestionOption {
  value: string
  label: string
}

export interface Question {
  id: string
  prompt: string
  why: string
  type: QuestionType
  required: boolean
  options: QuestionOption[]
}

export interface Questionnaire {
  questions: Question[]
}

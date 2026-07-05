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
  /** Profile id this question is aimed at (stamped by the backend). */
  audience: string
  /** Label for the "cannot answer — give a reason" control. */
  waiver_label: string
}

/** Lightweight profile descriptor for grouping and badging questions. */
export interface ProfileMeta {
  id: string
  label: string
  badge: string
}

/** A stakeholder profile that failed to contribute a questionnaire this
 *  round (crash, timeout, or empty response) — server-stamped.
 *  'soft' = still within its retry budget (retried on submit);
 *  'hard' = retries exhausted. */
export interface GenerationIssue {
  profile: string
  label: string
  reason: string
  severity: 'soft' | 'hard'
}

export interface Questionnaire {
  questions: Question[]
  profiles: ProfileMeta[]
  /** Profiles that failed to respond this round; shown in the gate. */
  issues?: GenerationIssue[]
}

/** A "cannot answer — recorded reason" answer (e.g. accepted risk). */
export interface WaiverAnswer {
  waived: true
  reason: string
}

/** A "none of these fit — here's what the agent got wrong" correction. */
export interface CustomAnswer {
  custom: string
}

/** A concrete answer with optional extra detail attached. */
export interface NotedAnswer {
  value: unknown
  note: string
}

/** Persisted working state of a refine interview. */
export interface InterviewEnvelope {
  questionnaire: Questionnaire
  draft_answers: Record<string, unknown>
}

/** An interview envelope tagged with its step's durable round counter. */
export interface PendingInterview extends InterviewEnvelope {
  round: number
}

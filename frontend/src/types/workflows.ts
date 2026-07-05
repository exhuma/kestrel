export interface WorkflowStep {
  name: string
  session_id: string | null
  status: string
  deliverable: string | null
  /** Monotonic counter bumped only on a genuine refine questionnaire change. */
  refine_round: number
}

/** A live session backing the active step, rendered as an activity chip. */
export interface StepSession {
  profile_id: string
  label: string
  badge: string
  session_id: string | null
  status: string
}

export interface WorkflowSummary {
  id: string
  repo: string
  issue_number: number
  status: string
}

export interface WorkflowDetail {
  id: string
  repo: string
  issue_number: number
  issue_title: string
  status: string
  branch: string
  steps: WorkflowStep[]
  current_session_id: string | null
  active_sessions: StepSession[]
  pr_url: string | null
  error: string | null
}

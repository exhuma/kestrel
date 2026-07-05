export interface WorkflowStep {
  name: string
  session_id: string | null
  status: string
  deliverable: string | null
  /** Monotonic counter bumped only on a genuine refine questionnaire change. */
  refine_round: number
  /** Backend id serving this step (e.g. "claude", "oc", "llm"). */
  backend: string
}

/** A live session backing the active step, rendered as an activity chip. */
export interface StepSession {
  profile_id: string
  label: string
  badge: string
  session_id: string | null
  status: string
  /** 1-2 word hint of the agent's current activity, live; null if idle. */
  activity: string | null
  /** When status is 'error', a short failure reason; null otherwise. */
  error: string | null
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
  /** Current dynamic refine round cap (grows per retry), for "Round N / cap". */
  refine_round_cap: number
  /** Absolute ceiling on refine rounds (retries included), for "(max M)". */
  refine_max_rounds: number
  pr_url: string | null
  error: string | null
}

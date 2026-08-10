/** The canonical workflow steps, mirroring the backend `Step` enum. */
export const STEPS = ['refine', 'design', 'code', 'verify'] as const
export type Step = (typeof STEPS)[number]

/** How the UI should render a step's deliverable. */
export type DeliverableFormat = 'diff' | 'markdown'

export interface WorkflowStep {
  name: string
  session_id: string | null
  status: string
  deliverable: string | null
  /** Monotonic counter bumped only on a genuine refine questionnaire change. */
  refine_round: number
  /** Code↔verify iterations the verify step has entered (1-based; 0 before). */
  verify_round: number
  /** Backend id serving this step (e.g. "claude", "oc", "llm"). */
  backend: string
  /** How to render `deliverable`: 'diff' (code step) or 'markdown'. */
  deliverable_format: DeliverableFormat
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

/** One frozen chip from a completed round (history) — the durable
 *  afterimage of a StepSession, unlike active_sessions which stays live
 *  only. */
export interface RoundChip {
  step: string
  /** 0-based group number within this step; consecutive chips sharing a
   *  round_index render as one group, separated from the next. */
  round_index: number
  profile_id: string
  label: string
  badge: string
  session_id: string | null
  /** Frozen terminal status: 'idle' (succeeded) or 'error' — never 'running'. */
  status: string
  error: string | null
  /** ISO timestamp of when this chip was frozen into history. */
  retired_at: string
}

/** A workflow screenshot (refine mockup or verify capture) for the gallery. */
export interface Screenshot {
  name: string
  stage: 'refine' | 'verify'
  /** Relative URL (under API_BASE) to fetch the image bytes. */
  url: string
}

export interface WorkflowSummary {
  id: string
  repo: string
  /** GitHub issue number; null for a Jira-sourced run (feature 003). */
  issue_number: number | null
  status: string
  /** Whether rerun is available (feature 008) — true only for a private
   *  task source (never GitHub/Jira). */
  rerunnable: boolean
}

export interface WorkflowDetail {
  id: string
  repo: string
  /** GitHub issue number; null for a Jira-sourced run (feature 003). */
  issue_number: number | null
  issue_title: string
  status: string
  branch: string
  steps: WorkflowStep[]
  current_session_id: string | null
  active_sessions: StepSession[]
  /** Frozen chips from every completed round of every step, oldest first. */
  round_history: RoundChip[]
  /** Current dynamic refine round cap (grows per retry), for "Round N / cap". */
  refine_round_cap: number
  /** Absolute ceiling on refine rounds (retries included), for "(max M)". */
  refine_max_rounds: number
  /** Configured cap on code↔verify iterations; drives the verify chip's
   *  "N runs left" progress circle together with a step's verify_round. */
  verify_max_iterations: number
  /** Safety net: allow submitting a questionnaire with required questions
   *  left unanswered (configured server-side). */
  allow_incomplete_answers: boolean
  /** Whether rerun is available (feature 008) — true only for a private
   *  task source (never GitHub/Jira). */
  rerunnable: boolean
  pr_url: string | null
  error: string | null
}

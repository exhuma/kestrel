/** The canonical workflow steps, mirroring the backend `Step` enum. */
export const STEPS = [
  'describe',
  'refine',
  'technical_analysis',
  'design',
  'code',
  'verify',
] as const
export type Step = (typeof STEPS)[number]

/** How the UI should render a step's deliverable. */
export type DeliverableFormat = 'diff' | 'markdown' | 'document'

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
  /** How to render `deliverable`: 'diff', 'document', or 'markdown'. */
  deliverable_format: DeliverableFormat
}

/** A live session backing the active step, rendered as an activity chip. */
export interface StepSession {
  profile_id: string
  label: string
  badge: string
  session_id: string | null
  status: string
  /** 1-2 word hint of the agent's current activity, live; null if idle/queued. */
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
  /** Short human-readable ticket identity from the task source (feature
   *  009), e.g. "owner/name#123", "RFC-123", "hello-fixture". */
  task_label: string
}

/** A resource created by this workflow that remains eligible for cleanup. */
export interface WorkflowArtifact {
  kind: string
  display_name: string
  cleanup_mode: string
  state: string
  error: string | null
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
  /** Short human-readable ticket identity from the task source (feature
   *  009), e.g. "owner/name#123", "RFC-123", "hello-fixture". */
  task_label: string
  /** Browser-navigable link to the ticket, or null when the source has
   *  none to offer (feature 009) — e.g. a fixture task. */
  task_link: string | null
  pr_url: string | null
  error: string | null
  artifacts: WorkflowArtifact[]
}

// --- Board domain (feature 026) --------------------------------------------
// Additive alongside the fixed-step types above (a clean-break replacement
// of them is a later phase, US6) — these mirror only what this slice's
// quarantine intervention needs. See specs/026-autonomous-work-board/
// contracts/board-api.md.

/** Safe, read-only view of a quarantine decision. Deliberately carries only
 *  safe metadata — never the raw suspect content that triggered the review
 *  (FR-025). Mirrors `app.schemas.SecurityReviewOut`. */
export interface SecurityReviewOut {
  id: string
  card_id: string
  workflow_id: string
  classification_category: string
  review_state: 'pending' | 'released' | 'discarded'
  resolution: string | null
}

/** Action names match the board-api.md `CardAction` vocabulary. Mirrors
 *  `app.schemas.QuarantineInterventionIn`. */
export type QuarantineAction = 'release_quarantine' | 'discard_quarantine'

/** The universal card states (board-api.md `CardState`). */
export const CARD_STATES = [
  'ready',
  'claimed',
  'waiting_dependency',
  'awaiting_human',
  'review',
  'quarantined',
  'done',
  'failed',
  'cancelled',
] as const
export type CardState = (typeof CARD_STATES)[number]

/** Operator interventions permitted against a card (board-api.md
 *  `CardAction`); a subset is served through the additive
 *  `/api/board/.../interventions` route (release/discard-quarantine stay
 *  on the dedicated security-review endpoint, see routers/board.py). */
export type CardAction =
  | 'retry'
  | 'cancel'
  | 'reassign'
  | 'resolve_gate'
  | 'request_coordinator_review'

/** Kinds of directed edge between two cards (board-api.md `RelationKind`). */
export type RelationKind = 'dependency' | 'reconciliation' | 'supersedes'

/** One specialist role reference. Mirrors `app.schemas.BoardRoleRefOut`. */
export interface BoardRoleRef {
  id: string
  label: string
}

/** The specialist currently holding a card's claim, if any. Mirrors
 *  `app.schemas.BoardOwnerOut`. */
export interface BoardOwner {
  specialist_id: string
  label: string
}

/** A claimed card's active lease. Mirrors `app.schemas.BoardLeaseOut`. */
export interface BoardLease {
  expires_at: string
  attempt: number
}

/** A safe pointer to a card's latest artifact — never its content.
 *  Mirrors `app.schemas.BoardArtifactRefOut`. */
export interface BoardArtifactRef {
  id: string
  label: string
  revision: number
}

/** One card's board-visible state. Mirrors `app.schemas.WorkCardSummaryOut`. */
export interface WorkCardSummary {
  id: string
  title: string
  card_type: string
  state: CardState
  eligible_roles: BoardRoleRef[]
  owner: BoardOwner | null
  lease: BoardLease | null
  waiting_reason: string | null
  dependency_count: number
  latest_artifact: BoardArtifactRef | null
  allowed_actions: CardAction[]
}

/** One directed edge in a workflow's card graph. Mirrors
 *  `app.schemas.WorkCardRelationOut`. */
export interface WorkCardRelation {
  card_id: string
  depends_on_card_id: string
  kind: RelationKind
}

/** One workflow's full board. Mirrors `app.schemas.BoardSnapshotOut`.
 *  `revision` is the optimistic-concurrency token every intervention
 *  against a card in this snapshot must echo back as `expected_revision`. */
export interface BoardSnapshot {
  id: string
  revision: number
  task_label: string
  status: string
  cards: WorkCardSummary[]
  relationships: WorkCardRelation[]
  state_counts: Partial<Record<CardState, number>>
}

/** One workflow's row in the board collection listing. Mirrors
 *  `app.schemas.WorkflowSummaryOut`. */
export interface BoardWorkflowSummary {
  id: string
  task_label: string
  status: string
  state_counts: Partial<Record<CardState, number>>
  action_required_count: number
}

/** Request body for one card intervention (board-api.md "Intervention").
 *  Mirrors `app.schemas.BoardInterventionIn`. */
export interface BoardInterventionRequest {
  action: CardAction
  expected_revision: number
  decision?: string | null
}

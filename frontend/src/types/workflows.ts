// --- Board domain (feature 026) --------------------------------------------
// See specs/026-autonomous-work-board/contracts/board-api.md.

/** Safe, read-only view of a quarantine decision. Deliberately carries only
 *  safe metadata — never the raw suspect content that triggered the review
 *  (FR-025). Mirrors `app.schemas.SecurityReviewOut`. */
export interface SecurityReviewOut {
  id: string
  card_id: string
  workflow_id: string
  classification_category: string
  reason: string | null
  review_state: 'pending' | 'released' | 'discarded'
  resolution: string | null
}

/** Action names match the board-api.md `CardAction` vocabulary. Mirrors
 *  `app.schemas.QuarantineInterventionIn`. */
export type QuarantineAction = 'release_quarantine' | 'discard_quarantine'

/** Request body for `POST /api/board/security-reviews/{id}/resolve`.
 *  Mirrors `app.schemas.QuarantineInterventionIn`. */
export interface QuarantineResolutionRequest {
  action: QuarantineAction
}

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
  /** The pending review this `security_review` card gates, when it has
   *  one — release/discard address `/api/board/security-reviews/{id}/
   *  resolve` directly, not the generic interventions route. */
  security_review_id: string | null
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

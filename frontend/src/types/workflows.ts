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
  /** The operator's own "I did this" on a `manual_task` card (feature 031). */
  | 'complete_manual_task'

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

/** One artifact's full content and trust level. Mirrors
 *  `app.schemas.BoardArtifactContentOut`. `content` is agent output
 *  crossing into the browser: never live markup (Markdown only through
 *  `lib/markdown`, feature 043) — and show `trust` visibly so
 *  `agent_output` is never mistaken for `operator_approved`. */
export interface BoardArtifactContent {
  content: string
  trust: string
  /** Absent from a response older than feature 043. */
  mime_type?: string
}

/** One board-history entry, safe for the narrative feed. Mirrors
 *  `app.schemas.BoardEventOut`. `specialist` is derived from the card's
 *  eligible role, not a recorded actor — `null` for a workflow-level
 *  event or an operator-resolved gate. */
export interface BoardEvent {
  event_type: string
  card_id: string | null
  payload: string
  created_at: string | null
  specialist: BoardRoleRef | null
}

/** Who decided a gate outside kestrel (feature 046): the payload of a
 *  `gate.approved` / `gate.rejected` event decided from the ticket.
 *  Mirrors `app.services.board.gate_decision.decision_payload`; a UI
 *  decision's payload is `{}`. */
export interface GateDecider {
  detail: string
  channel: string
  account_id: string
  display_name: string
}

/** A gate card's decision detail. Mirrors `app.schemas.WorkCardGateOut`.
 *  `requested_decision` tells an "approve/reject" gate apart from an
 *  "answer these questions" gate; `decision` is `null` until resolved.
 *  `round`/`cap` (feature 029 A3) are `null` for a gate that is not
 *  round-capped, and populated (1-based `round`) otherwise. */
export interface WorkCardGate {
  requested_decision: string
  decision: 'approved' | 'rejected' | null
  round: number | null
  cap: number | null
  /** What the gate asks about — the interview's questions, the PRD
   *  draft, the strategic-fit answers (#66). It belongs to the card that
   *  produced it, so it is never the gate card's own `latest_artifact`.
   *  `null` when the gate has no target. */
  target_artifact: BoardArtifactRef | null
  /** For an interview gate: the profile whose human answers it
   *  (feature 038). */
  persona: BoardRoleRef | null
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
  /** This card's gate decision detail, for a gate-kind card that has one
   *  recorded. */
  gate: WorkCardGate | null
  /** Who this card waits on, and for what (feature 035); `null` when it
   *  waits on nobody. */
  awaiting: Awaiting | null
}

/** Who a card waits on, and for what (feature 035). Mirrors
 *  `app.schemas.AwaitingOut`: codes the server decides; `lib/awaiting.ts`
 *  phrases them. `ask` is a gate's `requested_decision`, or `do_task`,
 *  `review_input`, `retry_or_cancel` or `review`. */
export interface Awaiting {
  actor: 'requester' | 'cab' | 'you' | 'operator' | 'role'
  ask: string
  /** For `role`: the profile whose human answers (feature 038). */
  role: BoardRoleRef | null
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
 *  against a card in this snapshot must echo back as `expected_revision`.
 *  `phase`/`stage` are a pure, derived, display-only projection — never a
 *  driver — see `app.services.board.phases`. */
/** What a request is doing right now (feature 033). Mirrors
 *  `app.schemas.RequestActivityOut`: the backend decides the state; the
 *  frontend phrases it (`lib/activity.ts`). */
export interface RequestActivity {
  state:
    | 'working'
    | 'problem'
    | 'waiting'
    | 'queued'
    | 'done'
    | 'cancelled'
    | 'stalled'
  /** Who is working, or who queued work is for. */
  actor: string | null
  /** The card concerned, by title. */
  subject: string | null
  /** For `problem`: the recorded, safe reason. */
  detail: string | null
  /** For `stalled`: why, as a code. */
  reason: 'interrupted_screening' | 'interrupted_claim' | 'nothing_ready' | null
  /** When this state began (UTC ISO), as far as is known. */
  since: string | null
  /** For `working`: the last tool the agent called (feature 036). */
  tool: string | null
  /** For `working`: how many tool calls the turn has made. */
  tool_calls: number | null
}

/** How a request stands overall (feature 040). Mirrors
 *  `app.schemas.Outcome`: the server decides; `done` only for a request
 *  that reached its end, never merely "every card is terminal". */
export type Outcome = 'in_progress' | 'done' | 'failed' | 'cancelled'

/** How one spine step stands (feature 034). Mirrors
 *  `app.schemas.PhaseStatusOut`; the server decides, the spine shows it. */
export type PhaseStatusValue =
  | 'done'
  | 'active'
  | 'waiting'
  | 'problem'
  | 'skipped'
  | 'cancelled'
  | 'upcoming'

export interface PhaseStatus {
  name: string
  status: PhaseStatusValue
}

export interface BoardSnapshot {
  id: string
  revision: number
  task_label: string
  /** Human title (feature 029 A2), falling back to `task_label` when
   *  unrecorded. */
  title: string
  status: string
  cards: WorkCardSummary[]
  relationships: WorkCardRelation[]
  state_counts: Partial<Record<CardState, number>>
  phase: string
  stage: string
  outcome: Outcome
  /** The request as screened once at intake (feature 030) — frozen since,
   *  so a later edit to the source ticket is not reflected. Snapshot only;
   *  never on the collection listing. */
  task_body: string
  /** Where delivery opened the change request (feature 043); `null`
   *  before delivery, or for one from before feature 043. */
  change_request_url: string | null
  /** What the request is doing right now (feature 033). */
  activity: RequestActivity | null
  /** Every spine step's status, in order (feature 034). Snapshot only. */
  phases: PhaseStatus[]
}

/** One workflow's row in the board collection listing. Mirrors
 *  `app.schemas.WorkflowSummaryOut`. `phase`/`stage` are the same
 *  derived, display-only projection as `BoardSnapshot`'s. */
export interface BoardWorkflowSummary {
  id: string
  task_label: string
  /** Human title (feature 029 A2), falling back to `task_label` when
   *  unrecorded. */
  title: string
  status: string
  state_counts: Partial<Record<CardState, number>>
  action_required_count: number
  phase: string
  stage: string
  outcome: Outcome
  /** Whether an interview round cap was hit without a usable answer
   *  (feature 029 A4) — the board's `cap-reached` treatment. */
  cap_exhausted: boolean
  /** How many `manual_task` cards are neither done nor cancelled
   *  (feature 031) — "N manual tasks assigned to you". */
  open_manual_task_count: number
  /** What the request is doing right now (feature 033). */
  activity: RequestActivity | null
  /** Every card waiting on a human, in card order (feature 035). */
  awaiting: Awaiting[]
}

/** Request body for one card intervention (board-api.md "Intervention").
 *  Mirrors `app.schemas.BoardInterventionIn`. */
export interface BoardInterventionRequest {
  action: CardAction
  expected_revision: number
  decision?: string | null
  /** Free-text response for a `resolve_gate` action — a `refinement_gate`'s
   *  answer, or a `prd_gate` rejection's feedback. Ignored otherwise. */
  answer?: string | null
}

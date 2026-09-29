/**
 * Stage-board pure logic (feature 029, US1): the six-stage/ten-phase
 * projection, per-card attention treatment, and grouping requests into
 * stage columns — one card per request (a request's approved tasks are
 * cards inside its own workflow, feature 031).
 *
 * Mirrors `app.services.board.phases` (stage/phase names) and
 * data-model.md §"AttentionState"/"BoardRequest". Pure and
 * display-only — never re-derives what the backend already decided
 * (Principle II): `stage`/`phase`/`cap_exhausted` are read verbatim off
 * `BoardWorkflowSummary`.
 */
import type { BoardWorkflowSummary } from '../types/workflows'

/** The six stages, in FR-001's order. */
export const STAGE_ORDER = [
  'Intake & alignment',
  'Discovery',
  'Definition',
  'Planning',
  'Build & deliver',
  'Done',
] as const

/** The ten phases, in sequence order (mirrors `app.services.board.phases`). */
export const PHASE_ORDER = [
  'Intake',
  'Understanding',
  'CAB-1 - strategic fit',
  'Pre-assessment',
  'PRD',
  'PRD sign-off',
  'Technical analysis',
  'CAB-2 - go/no-go',
  'Build',
  'Delivery',
] as const

/** A trailing column for a stage name the board has no fixed column for
 *  (edge case: a stage added on the backend before the frontend knows
 *  about it) — FR-002 guarantees the request still appears, not that it
 *  lands in one of the six named columns. */
const OTHER_STAGE = 'Other'

export interface PhasePosition {
  /** 1-based position within the ten-phase sequence, or `null` for an
   *  unrecognised phase (including the synthetic `"done"`). */
  ordinal: number | null
  isTerminal: boolean
}

/** A request's position in the ten-phase sequence (FR-004). */
export function phasePosition(phase: string): PhasePosition {
  const index = PHASE_ORDER.findIndex((p) => p === phase)
  return {
    ordinal: index === -1 ? null : index + 1,
    isTerminal: phase === 'done',
  }
}

export type AttentionState =
  | 'none'
  | 'your-move'
  | 'cap-reached'
  | 'quarantined'
  | 'done'

/** FR-005's three non-interchangeable treatments, plus the two
 *  non-attention states. Precedence: `quarantined` > `cap-reached` >
 *  `your-move` > `done` > `none` (data-model.md "AttentionState"). */
export function attentionOf(summary: BoardWorkflowSummary): AttentionState {
  if ((summary.state_counts.quarantined ?? 0) > 0) return 'quarantined'
  if (summary.cap_exhausted) return 'cap-reached'
  if (summary.action_required_count > 0) return 'your-move'
  if (summary.phase === 'done') return 'done'
  return 'none'
}

/** One board card: a request, its ten-phase position and its attention
 *  treatment (FR-002). */
export interface BoardRequest {
  summary: BoardWorkflowSummary
  position: PhasePosition
  attention: AttentionState
}

export interface StageColumn {
  stage: string
  requests: BoardRequest[]
}

function toBoardRequest(summary: BoardWorkflowSummary): BoardRequest {
  return {
    summary,
    position: phasePosition(summary.phase),
    attention: attentionOf(summary),
  }
}

/** Group ingested requests into the six stage columns (FR-001), one card
 *  per request (FR-002). An unrecognised stage name gets a trailing
 *  column instead of dropping the request. */
export function groupByStage(workflows: BoardWorkflowSummary[]): StageColumn[] {
  const buckets = new Map<string, BoardRequest[]>(
    STAGE_ORDER.map((stage) => [stage, []]),
  )
  const trailing: BoardRequest[] = []
  for (const summary of workflows) {
    const request = toBoardRequest(summary)
    const bucket = buckets.get(summary.stage)
    if (bucket) bucket.push(request)
    else trailing.push(request)
  }
  const columns: StageColumn[] = STAGE_ORDER.map((stage) => ({
    stage,
    requests: buckets.get(stage) ?? [],
  }))
  if (trailing.length > 0) {
    columns.push({ stage: OTHER_STAGE, requests: trailing })
  }
  return columns
}

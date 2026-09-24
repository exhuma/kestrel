import type { Edge, Node } from '@vue-flow/core'
import type { WorkCardRelation, WorkCardSummary } from '../types/workflows'

// Deterministic card/relation → graph projection (feature 026, US6). Only
// `dependency`-kind relations drive the layered layout (they're the only
// kind that gates readiness — see app.services.board.policy.
// dependencies_met); `reconciliation`/`supersedes` edges render as
// overlays without affecting node position, so the same board always
// lays out identically regardless of array order.

export interface BoardGraphNode {
  card: WorkCardSummary
}

const COLUMN_SPACING = 260
const ROW_SPACING = 110

export interface BoardGraph {
  nodes: Node<BoardGraphNode>[]
  edges: Edge[]
}

export function projectBoardGraph(
  cards: WorkCardSummary[],
  relationships: WorkCardRelation[],
): BoardGraph {
  const dependencyEdges = relationships.filter((r) => r.kind === 'dependency')
  const depths = computeDepths(cards, dependencyEdges)
  return {
    nodes: layoutNodes(cards, depths),
    edges: projectEdges(relationships),
  }
}

/** Each card's layer: 0 for a card with no dependency, else one past its
 *  deepest dependency. Cycle-safe (a cycle can't occur through policy,
 *  but this is a pure function over arbitrary snapshot data) — a card
 *  caught mid-cycle falls back to depth 0 rather than recursing forever. */
function computeDepths(
  cards: WorkCardSummary[],
  dependencyEdges: WorkCardRelation[],
): Map<string, number> {
  const dependsOn = new Map<string, string[]>()
  for (const edge of dependencyEdges) {
    const deps = dependsOn.get(edge.card_id) ?? []
    deps.push(edge.depends_on_card_id)
    dependsOn.set(edge.card_id, deps)
  }
  const depths = new Map<string, number>()
  const visiting = new Set<string>()
  const depthOf = (cardId: string): number => {
    if (depths.has(cardId)) return depths.get(cardId) as number
    if (visiting.has(cardId)) return 0
    visiting.add(cardId)
    const deps = dependsOn.get(cardId) ?? []
    const depth = deps.length === 0 ? 0 : 1 + Math.max(...deps.map(depthOf))
    visiting.delete(cardId)
    depths.set(cardId, depth)
    return depth
  }
  for (const card of cards) depthOf(card.id)
  return depths
}

function layoutNodes(
  cards: WorkCardSummary[],
  depths: Map<string, number>,
): Node<BoardGraphNode>[] {
  const sorted = [...cards].sort((a, b) => a.id.localeCompare(b.id))
  const rowByDepth = new Map<number, number>()
  return sorted.map((card) => {
    const depth = depths.get(card.id) ?? 0
    const row = rowByDepth.get(depth) ?? 0
    rowByDepth.set(depth, row + 1)
    return {
      id: card.id,
      position: { x: depth * COLUMN_SPACING, y: row * ROW_SPACING },
      data: { card },
    }
  })
}

function projectEdges(relationships: WorkCardRelation[]): Edge[] {
  return relationships.map((r) => ({
    id: `${r.kind}:${r.card_id}->${r.depends_on_card_id}`,
    source: r.depends_on_card_id,
    target: r.card_id,
    type: r.kind === 'dependency' ? undefined : 'step',
    label: r.kind === 'dependency' ? undefined : r.kind,
    animated: r.kind === 'reconciliation',
  }))
}

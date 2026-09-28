import { describe, it, expect } from 'vitest'
import { projectBoardGraph } from '../../src/lib/boardGraph'
import type {
  WorkCardRelation,
  WorkCardSummary,
} from '../../src/types/workflows'

function card(
  id: string,
  overrides: Partial<WorkCardSummary> = {},
): WorkCardSummary {
  return {
    id,
    title: id,
    card_type: 'analysis',
    state: 'ready',
    eligible_roles: [],
    owner: null,
    lease: null,
    waiting_reason: null,
    dependency_count: 0,
    latest_artifact: null,
    allowed_actions: [],
    security_review_id: null,
    gate: null,
    ...overrides,
  }
}

function dependency(cardId: string, dependsOnCardId: string): WorkCardRelation {
  return {
    card_id: cardId,
    depends_on_card_id: dependsOnCardId,
    kind: 'dependency',
  }
}

describe('projectBoardGraph nodes', () => {
  it('produces one node per card', () => {
    const graph = projectBoardGraph([card('a'), card('b')], [])
    expect(graph.nodes.map((n) => n.id).sort()).toEqual(['a', 'b'])
  })

  it('places a root card (no dependencies) at column 0', () => {
    const graph = projectBoardGraph([card('a')], [])
    expect(graph.nodes[0].position.x).toBe(0)
  })

  it('places a dependent card one column past its dependency', () => {
    const graph = projectBoardGraph(
      [card('a'), card('b')],
      [dependency('b', 'a')],
    )
    const a = graph.nodes.find((n) => n.id === 'a')
    const b = graph.nodes.find((n) => n.id === 'b')
    expect(b!.position.x).toBeGreaterThan(a!.position.x)
  })

  it('places a two-hop dependent two columns past the root', () => {
    const graph = projectBoardGraph(
      [card('a'), card('b'), card('c')],
      [dependency('b', 'a'), dependency('c', 'b')],
    )
    const columnOf = (id: string) =>
      graph.nodes.find((n) => n.id === id)!.position.x
    expect(columnOf('c')).toBeGreaterThan(columnOf('b'))
    expect(columnOf('b')).toBeGreaterThan(columnOf('a'))
  })

  it('places same-depth cards in different rows', () => {
    const graph = projectBoardGraph([card('a'), card('b')], [])
    const rows = graph.nodes.map((n) => n.position.y)
    expect(new Set(rows).size).toBe(2)
  })

  it('is deterministic regardless of input array order', () => {
    const first = projectBoardGraph([card('a'), card('b')], [])
    const second = projectBoardGraph([card('b'), card('a')], [])
    expect(first.nodes).toEqual(second.nodes)
  })

  it('carries the full card summary as node data', () => {
    const graph = projectBoardGraph([card('a', { title: 'Investigate' })], [])
    expect(graph.nodes[0].data?.card.title).toBe('Investigate')
  })

  it('does not throw on a cyclic relation graph', () => {
    const graph = projectBoardGraph(
      [card('a'), card('b')],
      [dependency('a', 'b'), dependency('b', 'a')],
    )
    expect(graph.nodes).toHaveLength(2)
  })
})

describe('projectBoardGraph edges', () => {
  it('projects a dependency relation as an edge from dependency to card', () => {
    const graph = projectBoardGraph(
      [card('a'), card('b')],
      [dependency('b', 'a')],
    )
    expect(graph.edges).toEqual([
      expect.objectContaining({ source: 'a', target: 'b' }),
    ])
  })

  it('labels a non-dependency relation with its kind', () => {
    const graph = projectBoardGraph(
      [card('a'), card('b')],
      [{ card_id: 'b', depends_on_card_id: 'a', kind: 'reconciliation' }],
    )
    expect(graph.edges[0].label).toBe('reconciliation')
  })

  it('leaves a dependency edge unlabeled', () => {
    const graph = projectBoardGraph(
      [card('a'), card('b')],
      [dependency('b', 'a')],
    )
    expect(graph.edges[0].label).toBeUndefined()
  })
})

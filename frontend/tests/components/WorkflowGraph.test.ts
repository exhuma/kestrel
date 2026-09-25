import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import WorkflowGraph from '../../src/components/WorkflowGraph.vue'
import type {
  WorkCardRelation,
  WorkCardSummary,
} from '../../src/types/workflows'

// Vue Flow needs real DOM dimensions to render its node/edge elements
// (it culls anything outside the measured viewport), which jsdom/happy-dom
// never provide — so these tests drive the underlying VueFlow component
// directly (props in, events out) rather than asserting on rendered node
// DOM. The projection itself (which nodes/edges exist, their layout) is
// covered by boardGraph.test.ts.

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

function mountGraph(
  cards: WorkCardSummary[],
  relationships: WorkCardRelation[] = [],
) {
  return mount(WorkflowGraph, withVuetify({ props: { cards, relationships } }))
}

describe('WorkflowGraph projection wiring', () => {
  it('passes one Vue Flow node per card', () => {
    const wrapper = mountGraph([card('a'), card('b')])
    const flow = wrapper.findComponent({ name: 'VueFlow' })
    const nodes = flow.props('nodes') as { id: string }[]
    expect(nodes.map((n) => n.id).sort()).toEqual(['a', 'b'])
  })

  it('passes one Vue Flow edge per relation', () => {
    const wrapper = mountGraph([card('a'), card('b')], [dependency('b', 'a')])
    const flow = wrapper.findComponent({ name: 'VueFlow' })
    const edges = flow.props('edges') as { source: string; target: string }[]
    expect(edges).toEqual([
      expect.objectContaining({ source: 'a', target: 'b' }),
    ])
  })

  it('marks itself read-only via an application role', () => {
    const wrapper = mountGraph([card('a')])
    expect(wrapper.get('[role="application"]').attributes('aria-label')).toBe(
      'Workflow dependency graph',
    )
  })
})

describe('WorkflowGraph selection', () => {
  it('emits select with the card id when Vue Flow reports a node click', () => {
    const wrapper = mountGraph([card('a')])
    const flow = wrapper.findComponent({ name: 'VueFlow' })
    flow.vm.$emit('node-click', { node: { id: 'a' } })
    expect(wrapper.emitted('select')).toEqual([['a']])
  })
})

describe('WorkflowGraph no-mutation interaction', () => {
  it('never renders a draggable/connectable Vue Flow instance', () => {
    const wrapper = mountGraph([card('a')])
    const flow = wrapper.findComponent({ name: 'VueFlow' })
    expect(flow.props('nodesDraggable')).toBe(false)
    expect(flow.props('nodesConnectable')).toBe(false)
    expect(flow.props('edgesUpdatable')).toBe(false)
  })
})

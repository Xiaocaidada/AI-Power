import { describe, expect, test } from 'vitest'

import {
  applyBuilderSelection,
  defaultBuilderSelection,
  edgeChangeKey,
  nodeChangeKey,
} from './builderApply'
import type { AgentBuilderDiff, WorkflowDefinition } from './types'

const current: WorkflowDefinition = {
  nodes: [
    { id: 'start', type: 'start', config: {} },
    { id: 'old', type: 'llm', config: {} },
    { id: 'out', type: 'output', config: {} },
  ],
  edges: [
    { from: 'start', to: 'old' },
    { from: 'old', to: 'out' },
  ],
}

const target: WorkflowDefinition = {
  nodes: [
    { id: 'start', type: 'start', config: {} },
    { id: 'new', type: 'llm', config: { prompt: 'hi' } },
    { id: 'out', type: 'output', config: {} },
  ],
  edges: [
    { from: 'start', to: 'new' },
    { from: 'new', to: 'out' },
  ],
}

const diff: AgentBuilderDiff = {
  added_nodes: [{ id: 'new', type: 'llm' }],
  removed_nodes: [{ id: 'old', type: 'llm' }],
  updated_nodes: [],
  added_edges: [
    { from: 'start', to: 'new' },
    { from: 'new', to: 'out' },
  ],
  removed_edges: [
    { from: 'start', to: 'old' },
    { from: 'old', to: 'out' },
  ],
}

describe('builder partial apply', () => {
  test('applies the complete diff by default', () => {
    const applied = applyBuilderSelection(
      current,
      target,
      diff,
      defaultBuilderSelection(diff),
    )
    expect(applied.nodes.map((node) => node.id)).toEqual(['start', 'out', 'new'])
    expect(applied.edges).toHaveLength(2)
  })

  test('keeps unselected changes out of the result', () => {
    const selected = defaultBuilderSelection(diff)
    selected.delete(nodeChangeKey('add', 'new'))
    selected.delete(nodeChangeKey('remove', 'old'))
    selected.delete(edgeChangeKey('remove', { from: 'start', to: 'old' }))
    selected.delete(edgeChangeKey('remove', { from: 'old', to: 'out' }))
    const applied = applyBuilderSelection(current, target, diff, selected)
    expect(applied.nodes.map((node) => node.id)).toContain('old')
    expect(applied.nodes.map((node) => node.id)).not.toContain('new')
    expect(applied.edges).toEqual([
      { from: 'start', to: 'old' },
      { from: 'old', to: 'out' },
    ])
  })

  test('selection only containing added node keeps existing edges', () => {
    const selected = new Set([nodeChangeKey('add', 'new')])
    const applied = applyBuilderSelection(current, target, diff, selected)
    expect(applied.nodes.map((node) => node.id)).toEqual([
      'start',
      'old',
      'out',
      'new',
    ])
    expect(applied.edges).toEqual([
      { from: 'start', to: 'old' },
      { from: 'old', to: 'out' },
    ])
  })
})
import type {
  AgentBuilderDiff,
  WorkflowDefinition,
  WorkflowEdgeDefinition,
} from './types'

export function nodeChangeKey(
  action: 'add' | 'remove' | 'update',
  nodeId: string,
): string {
  return `node:${action}:${nodeId}`
}

export function edgeChangeKey(
  action: 'add' | 'remove',
  edge: { from: string; to: string; when?: string | null },
): string {
  return `edge:${action}:${edge.from}->${edge.to}:${edge.when ?? ''}`
}

export function defaultBuilderSelection(diff: AgentBuilderDiff): Set<string> {
  const selected = new Set<string>()
  for (const node of diff.added_nodes) {
    selected.add(nodeChangeKey('add', node.id))
  }
  for (const node of diff.removed_nodes) {
    selected.add(nodeChangeKey('remove', node.id))
  }
  for (const node of diff.updated_nodes) {
    selected.add(nodeChangeKey('update', node.id))
  }
  for (const edge of diff.added_edges) {
    selected.add(edgeChangeKey('add', edge))
  }
  for (const edge of diff.removed_edges) {
    selected.add(edgeChangeKey('remove', edge))
  }
  return selected
}

function edgeMatches(
  left: WorkflowEdgeDefinition,
  right: { from: string; to: string; when?: string | null },
): boolean {
  return (
    left.from === right.from &&
    left.to === right.to &&
    (left.when ?? null) === (right.when ?? null)
  )
}

export function applyBuilderSelection(
  current: WorkflowDefinition,
  target: WorkflowDefinition,
  diff: AgentBuilderDiff,
  selected: Set<string>,
): WorkflowDefinition {
  const nodes = new Map(current.nodes.map((node) => [node.id, node]))
  for (const node of diff.removed_nodes) {
    if (selected.has(nodeChangeKey('remove', node.id))) {
      nodes.delete(node.id)
    }
  }
  for (const node of diff.added_nodes) {
    if (!selected.has(nodeChangeKey('add', node.id))) continue
    const full = target.nodes.find((item) => item.id === node.id)
    if (full !== undefined) nodes.set(full.id, full)
  }
  for (const node of diff.updated_nodes) {
    if (!selected.has(nodeChangeKey('update', node.id))) continue
    const full = target.nodes.find((item) => item.id === node.id)
    if (full !== undefined) nodes.set(full.id, full)
  }
  let edges = current.edges.filter(
    (edge) =>
      !diff.removed_edges.some(
        (removed) =>
          selected.has(edgeChangeKey('remove', removed)) &&
          edgeMatches(edge, removed),
      ),
  )
  for (const edge of diff.added_edges) {
    if (!selected.has(edgeChangeKey('add', edge))) continue
    if (edges.some((existing) => edgeMatches(existing, edge))) continue
    edges.push({
      from: edge.from,
      to: edge.to,
      ...(edge.when ? { when: edge.when as 'true' | 'false' } : {}),
    })
  }
  edges = edges.filter((edge) => nodes.has(edge.from) && nodes.has(edge.to))
  return { nodes: [...nodes.values()], edges }
}
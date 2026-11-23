import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Waypoints } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  MemoryCategory,
  MemoryGraph,
  MemoryGraphNode,
} from '../../lib/types'

const CATEGORIES: MemoryCategory[] = [
  'preference',
  'profile',
  'project',
  'technical',
  'experience',
  'decision',
  'relation',
  'fact',
]

interface MemoryGraphPanelProps {
  onOpenMemory: (memoryId: string) => void
}

type GraphNode = Node<{ label: string; memoryId?: string }>

function nodeStyle(type: MemoryGraphNode['type']): Record<string, string | number> {
  const base = {
    borderRadius: 14,
    padding: 8,
    fontSize: 11,
    width: 168,
    color: 'rgb(var(--ink))',
    boxShadow: '0 1px 2px rgb(0 0 0 / 0.08)',
  }
  if (type === 'memory') {
    return {
      ...base,
      background: 'rgb(var(--surface))',
      border: '2px solid rgb(var(--accent))',
    }
  }
  if (type === 'project') {
    return {
      ...base,
      background: 'rgb(var(--accent-soft))',
      border: '1px solid rgb(var(--accent))',
    }
  }
  return {
    ...base,
    background: 'rgb(var(--surface-muted))',
    border: '1px dashed rgb(var(--border))',
  }
}

function layout(nodes: MemoryGraphNode[]): Map<string, { x: number; y: number }> {
  const center = { x: 680, y: 430 }
  const memories = nodes.filter((node) => node.type === 'memory')
  const external = nodes.filter((node) => node.type !== 'memory')
  const positions = new Map<string, { x: number; y: number }>()
  const memoryRadius = Math.max(
    190,
    Math.min(520, (memories.length * 72) / (2 * Math.PI) + 120),
  )
  memories.forEach((node, index) => {
    const angle =
      -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(memories.length, 1)
    positions.set(node.id, {
      x: center.x + memoryRadius * Math.cos(angle),
      y: center.y + memoryRadius * Math.sin(angle),
    })
  })
  const externalRadius = memoryRadius + 210
  external.forEach((node, index) => {
    const angle =
      -Math.PI / 2 + 0.4 + (index * 2 * Math.PI) / Math.max(external.length, 1)
    positions.set(node.id, {
      x: center.x + externalRadius * Math.cos(angle),
      y: center.y + externalRadius * Math.sin(angle),
    })
  })
  return positions
}

export function MemoryGraphPanel({ onOpenMemory }: MemoryGraphPanelProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [scopeType, setScopeType] = useState('')
  const [category, setCategory] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState('')
  const [localOnly, setLocalOnly] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)

  const graph = useQuery({
    queryKey: ['memory-graph', scopeType, category, search],
    queryFn: () =>
      apiRequest<MemoryGraph>(
        `/memories/graph?${new URLSearchParams({
          ...(scopeType !== '' ? { scope_type: scopeType } : {}),
          ...(category !== '' ? { category } : {}),
          ...(search.trim() !== '' ? { q: search.trim() } : {}),
        }).toString()}`,
      ),
  })

  const flow = useMemo(() => {
    const data = graph.data
    if (data === undefined) return { nodes: [] as GraphNode[], edges: [] as Edge[] }
    let edges = data.edges
    let nodes = data.nodes
    if (localOnly && selected !== '') {
      const visible = new Set<string>([selected])
      for (const edge of edges) {
        if (edge.source === selected) visible.add(edge.target)
        if (edge.target === selected) visible.add(edge.source)
      }
      nodes = nodes.filter((node) => visible.has(node.id))
      edges = edges.filter(
        (edge) => visible.has(edge.source) && visible.has(edge.target),
      )
    }
    const positions = layout(nodes)
    return {
      nodes: nodes.map((node) => ({
        id: node.id,
        position: positions.get(node.id) ?? { x: 0, y: 0 },
        data: {
          label:
            node.type === 'memory'
              ? `${node.label}${node.category ? ` · ${t(`memory.category.${node.category}`)}` : ''}`
              : node.label,
          memoryId: node.memory_id ?? undefined,
        },
        style: nodeStyle(node.type),
      })),
      edges: edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.relation_type === 'related' ? undefined : edge.relation_type,
        style: {
          stroke:
            edge.source_kind === 'auto'
              ? 'rgb(var(--accent) / 0.55)'
              : 'rgb(var(--ink-muted))',
          strokeDasharray: edge.source_kind === 'auto' ? '5 4' : undefined,
        },
        labelStyle: { fill: 'rgb(var(--ink-muted))', fontSize: 10 },
      })),
    }
  }, [graph.data, localOnly, selected, t])

  const rebuild = async () => {
    setRebuilding(true)
    try {
      await apiRequest('/memories/graph/rebuild', { method: 'POST' })
      await queryClient.invalidateQueries({ queryKey: ['memory-graph'] })
      await queryClient.invalidateQueries({ queryKey: ['memory-relations'] })
    } finally {
      setRebuilding(false)
    }
  }

  if (graph.isLoading) {
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    )
  }

  const stats = graph.data?.stats
  const empty = (graph.data?.nodes ?? []).length === 0

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t('memory.graph.search')}
          className="h-9 w-full max-w-xs rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
        />
        <select
          value={scopeType}
          onChange={(event) => setScopeType(event.target.value)}
          className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
        >
          <option value="">{t('memory.allScopes')}</option>
          <option value="global">{t('memory.scopeType.global')}</option>
          <option value="project">{t('memory.scopeType.project')}</option>
          <option value="agent">{t('memory.scopeType.agent')}</option>
        </select>
        <select
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
        >
          <option value="">{t('memory.allCategories')}</option>
          {CATEGORIES.map((item) => (
            <option key={item} value={item}>
              {t(`memory.category.${item}`)}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-xs text-ink-muted">
          <input
            type="checkbox"
            checked={localOnly}
            disabled={selected === ''}
            onChange={(event) => setLocalOnly(event.target.checked)}
          />
          {t('memory.graph.localOnly')}
        </label>
        <Button
          size="sm"
          variant="secondary"
          disabled={rebuilding}
          onClick={() => void rebuild()}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t('memory.graph.rebuild')}
        </Button>
      </div>

      {stats !== undefined && (
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="accent">
            {t('memory.graph.memories')}: {stats.memories}
          </Badge>
          <Badge tone="neutral">
            {t('memory.graph.external')}: {stats.external}
          </Badge>
          <Badge tone="neutral">
            {t('memory.graph.relations')}: {stats.relations}
          </Badge>
          <Badge tone={stats.orphans > 0 ? 'warning' : 'neutral'}>
            {t('memory.graph.orphans')}: {stats.orphans}
          </Badge>
          {selected !== '' && (
            <Button size="sm" variant="ghost" onClick={() => setSelected('')}>
              {t('memory.graph.clearSelection')}
            </Button>
          )}
        </div>
      )}

      {empty ? (
        <EmptyState
          title={t('memory.graph.empty')}
          description={t('memory.graph.emptyLead')}
        />
      ) : (
        <div className="h-[620px] overflow-hidden rounded-card border border-border bg-canvas">
          <ReactFlow
            key={`${graph.dataUpdatedAt}-${selected}-${localOnly}`}
            nodes={flow.nodes}
            edges={flow.edges}
            fitView
            minZoom={0.2}
            maxZoom={1.8}
            nodesDraggable
            onNodeClick={(_, node) => {
              setSelected(node.id)
              const memoryId = node.data.memoryId
              if (memoryId) onOpenMemory(String(memoryId))
            }}
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={20} color="rgb(var(--border))" />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable nodeStrokeWidth={2} />
          </ReactFlow>
        </div>
      )}

      <p className="flex items-center gap-1.5 text-[11px] text-ink-muted">
        <Waypoints className="h-3 w-3" />
        {t('memory.graph.hint')}
      </p>
    </div>
  )
}
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  Bot,
  BookOpen,
  Brain,
  Boxes,
  Code,
  Database,
  Eraser,
  Scissors,
  FileText,
  Flag,
  GitBranch,
  GitFork,
  GitMerge,
  Globe,
  MessageSquare,
  Play,
  Plug,
  Repeat,
  Save,
  Sparkles,
  UserCheck,
  Wrench,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { Button } from '../../components/ui/button'
import { useI18n } from '../../lib/i18n'
import type { WorkflowCatalog, WorkflowDefinition } from '../../lib/types'
import { StudioNodePanel } from './StudioNodePanel'
import type { StudioNodeData, StudioResources } from './types'

type StudioNode = Node<StudioNodeData>

const ICONS = {
  start: Play,
  llm: Sparkles,
  agent: Bot,
  kb_search: BookOpen,
  tool: Wrench,
  condition: GitBranch,
  parallel: GitFork,
  join: GitMerge,
  output: Flag,
  review: UserCheck,
  loop: Repeat,
  http: Globe,
  mcp: Plug,
  memory_read: Brain,
  memory_write: Save,
  code: Code,
  database: Database,
  mcp_resource: FileText,
  mcp_prompt: MessageSquare,
  parse_document: FileText,
  clean_text: Eraser,
  chunk_text: Scissors,
  embed_chunks: Boxes,
  index_knowledge: Database,
}

function StudioNodeCard({ data, selected }: NodeProps<StudioNode>) {
  const Icon = ICONS[data.nodeType] ?? Sparkles
  return (
    <div
      className={`min-w-40 rounded-xl border bg-surface px-3 py-2 shadow-subtle ${
        selected ? 'border-accent ring-2 ring-accent/20' : 'border-border'
      }`}
    >
      <Handle type="target" position={Position.Left} className="!bg-accent" />
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <Icon className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-ink">{data.label}</p>
          <p className="text-[10px] text-ink-muted">{data.nodeType}</p>
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-accent" />
    </div>
  )
}

const nodeTypes = { studio: StudioNodeCard }

function toRfNodes(definition: WorkflowDefinition, catalog: WorkflowCatalog): StudioNode[] {
  return definition.nodes.map((node, index) => {
    const meta = catalog.nodes.find((item) => item.type === node.type)
    return {
      id: node.id,
      type: 'studio',
      position: node.ui ?? { x: 80 + index * 220, y: 140 },
      data: {
        nodeType: node.type,
        label: meta?.label ?? node.type,
        config: { ...node.config },
      },
    }
  })
}

function toRfEdges(definition: WorkflowDefinition): Edge[] {
  return definition.edges.map((edge, index) => ({
    id: `${edge.from}-${edge.to}-${index}`,
    source: edge.from,
    target: edge.to,
    label: edge.when ?? undefined,
    data: { when: edge.when ?? undefined },
  }))
}

function toDefinition(nodes: StudioNode[], edges: Edge[]): WorkflowDefinition {
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      type: node.data.nodeType,
      config: node.data.config,
      ui: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
    })),
    edges: edges.map((edge) => ({
      from: edge.source,
      to: edge.target,
      ...(typeof edge.data?.when === 'string'
        ? { when: edge.data.when as 'true' | 'false' }
        : {}),
    })),
  }
}

interface StudioCanvasProps {
  initialDefinition: WorkflowDefinition
  seed: number
  catalog: WorkflowCatalog | undefined
  resources: StudioResources
  saving: boolean
  error: string | null
  onSave: (definition: WorkflowDefinition) => void
}

export function StudioCanvas({
  initialDefinition,
  seed,
  catalog,
  resources,
  saving,
  error,
  onSave,
}: StudioCanvasProps) {
  const { t } = useI18n()
  const [nodes, setNodes, onNodesChange] = useNodesState<StudioNode>(
    toRfNodes(initialDefinition, catalog ?? { nodes: [], limits: { max_nodes: 30, max_kbs: 10 }, variables: {} }),
  )
  const [edges, setEdges, onEdgesChange] = useEdgesState(toRfEdges(initialDefinition))
  const [selectedId, setSelectedId] = useState('')

  useEffect(() => {
    if (catalog === undefined) return
    setNodes(toRfNodes(initialDefinition, catalog))
    setEdges(toRfEdges(initialDefinition))
    setSelectedId('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed, catalog])

  const selectedNode = nodes.find((node) => node.id === selectedId)
  const selectedMeta = catalog?.nodes.find(
    (item) => item.type === selectedNode?.data.nodeType,
  )
  const nodeOptions = useMemo(() => catalog?.nodes ?? [], [catalog])

  const addNode = (type: StudioNodeData['nodeType'], position?: { x: number; y: number }) => {
    const meta = catalog?.nodes.find((item) => item.type === type)
    const id = `${type}_${Date.now().toString(36)}`
    setNodes((prev) => [
      ...prev,
      {
        id,
        type: 'studio',
        position: position ?? { x: 120 + prev.length * 24, y: 120 + prev.length * 18 },
        data: {
          nodeType: type,
          label: meta?.label ?? type,
          config: {},
        },
      },
    ])
    setSelectedId(id)
  }

  const onConnect = (connection: Connection) => {
    const source = nodes.find((node) => node.id === connection.source)
    const when = source?.data.nodeType === 'condition' ? 'true' : undefined
    setEdges((prev) =>
      addEdge(
        {
          ...connection,
          label: when,
          data: { when },
        },
        prev,
      ),
    )
  }

  const updateConfig = (config: Record<string, unknown>) => {
    if (selectedNode === undefined) return
    setNodes((prev) =>
      prev.map((node) =>
        node.id === selectedNode.id
          ? { ...node, data: { ...node.data, config } }
          : node,
      ),
    )
  }

  const updateEdgeWhen = (edgeId: string, when: 'true' | 'false') => {
    setEdges((prev) =>
      prev.map((edge) =>
        edge.id === edgeId
          ? { ...edge, label: when, data: { ...edge.data, when } }
          : edge,
      ),
    )
  }

  const removeNode = () => {
    if (selectedNode === undefined) return
    setNodes((prev) => prev.filter((node) => node.id !== selectedNode.id))
    setEdges((prev) =>
      prev.filter(
        (edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id,
      ),
    )
    setSelectedId('')
  }

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-44 shrink-0 overflow-y-auto border-r border-border bg-surface px-2 py-3">
        <p className="px-1 text-xs font-medium text-ink">{t('studio.nodePalette')}</p>
        <div className="mt-2 space-y-1">
          {nodeOptions.map((item) => {
            const Icon = ICONS[item.type] ?? Sparkles
            return (
              <button
                key={item.type}
                type="button"
                draggable
                onDragStart={(event) => {
                  event.dataTransfer.setData('application/studio-node', item.type)
                  event.dataTransfer.effectAllowed = 'move'
                }}
                onClick={() => addNode(item.type)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-ink-muted hover:bg-surface-muted hover:text-ink"
              >
                <Icon className="h-3.5 w-3.5" />
                <span className="truncate">{item.label}</span>
              </button>
            )
          })}
        </div>
      </aside>

      <section className="relative min-w-0 flex-1">
        <div
          className="h-full"
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault()
            const type = event.dataTransfer.getData(
              'application/studio-node',
            ) as StudioNodeData['nodeType']
            if (!type) return
            addNode(type, { x: event.nativeEvent.offsetX, y: event.nativeEvent.offsetY })
          }}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, node) => setSelectedId(node.id)}
            onPaneClick={() => setSelectedId('')}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background gap={18} size={1} />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
        <div className="absolute bottom-4 left-4 z-10 flex items-center gap-2">
          <Button
            size="sm"
            disabled={saving}
            onClick={() => onSave(toDefinition(nodes, edges))}
          >
            <Save className="h-3.5 w-3.5" />
            {t('studio.saveCanvas')}
          </Button>
          {error !== null && (
            <span className="rounded bg-surface px-2 py-1 text-xs text-danger">{error}</span>
          )}
        </div>
      </section>

      <aside className="w-80 shrink-0 overflow-y-auto border-l border-border bg-surface">
        {selectedNode !== undefined ? (
          <StudioNodePanel
            node={selectedNode}
            meta={selectedMeta}
            edges={edges.filter((edge) => edge.source === selectedNode.id)}
            resources={resources}
            onChange={updateConfig}
            onEdgeWhen={updateEdgeWhen}
            onRemove={removeNode}
          />
        ) : (
          <div className="p-4">
            <p className="text-sm font-medium text-ink">{t('studio.inspector')}</p>
            <p className="mt-1 text-xs text-ink-muted">{t('studio.inspectorHint')}</p>
          </div>
        )}
      </aside>
    </div>
  )
}
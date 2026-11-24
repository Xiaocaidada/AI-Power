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
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  Bot,
  BookOpen,
  Brain,
  Boxes,
  Code,
  Copy,
  Database,
  Download,
  Eraser,
  FileText,
  Filter,
  Flag,
  GitBranch,
  GitFork,
  GitMerge,
  Globe,
  Layers,
  ListOrdered,
  MessageSquare,
  Play,
  Plug,
  Redo2,
  RefreshCw,
  Repeat,
  Save,
  ScanText,
  Scissors,
  Sparkles,
  Tags,
  Undo2,
  Upload,
  UserCheck,
  Wrench,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Button } from '../../components/ui/button'
import {
  emptyHistory,
  recordHistory,
  redoHistory,
  undoHistory,
  type CanvasHistory,
} from '../../lib/canvasHistory'
import { useI18n } from '../../lib/i18n'
import type {
  WorkflowCatalog,
  WorkflowDefinition,
  WorkflowVersion,
} from '../../lib/types'
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
  multi_query: Sparkles,
  intent_classify: Brain,
  synonym_expand: Sparkles,
  filter_results: Filter,
  fallback_search: RefreshCw,
  http: Globe,
  mcp: Plug,
  memory_read: Brain,
  memory_write: Save,
  code: Code,
  database: Database,
  mcp_resource: FileText,
  mcp_prompt: MessageSquare,
  parse_document: FileText,
  ocr_document: ScanText,
  clean_text: Eraser,
  filter_text: Filter,
  chunk_text: Scissors,
  enrich_metadata: Tags,
  extract_keywords: Tags,
  summarize_chunks: FileText,
  dedupe_chunks: Copy,
  embed_chunks: Boxes,
  index_knowledge: Database,
  rewrite_query: Sparkles,
  vector_search: Boxes,
  lexical_search: FileText,
  hybrid_search: GitMerge,
  rerank: ListOrdered,
  top_k: Filter,
  context: Layers,
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
  versions?: WorkflowVersion[]
  workflowId?: string | null
  version?: number
  debuggable?: boolean
  onSave: (definition: WorkflowDefinition) => void
  onRestoreVersion?: (version: number) => void | Promise<void>
  onAutosave?: (definition: WorkflowDefinition) => void | Promise<void>
}

export function StudioCanvas({
  initialDefinition,
  seed,
  catalog,
  resources,
  saving,
  error,
  versions = [],
  workflowId = null,
  version,
  debuggable = false,
  onSave,
  onRestoreVersion,
  onAutosave,
}: StudioCanvasProps) {
  const { t } = useI18n()
  const [nodes, setNodes, onNodesChange] = useNodesState<StudioNode>(
    toRfNodes(initialDefinition, catalog ?? { nodes: [], limits: { max_nodes: 30, max_kbs: 10 }, variables: {} }),
  )
  const [edges, setEdges, onEdgesChange] = useEdgesState(toRfEdges(initialDefinition))
  const [selectedId, setSelectedId] = useState('')
  const [history, setHistory] = useState<CanvasHistory<WorkflowDefinition>>(
    emptyHistory(),
  )
  const [targetVersion, setTargetVersion] = useState<number | ''>('')
  const [restoring, setRestoring] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [draftState, setDraftState] = useState<
    'idle' | 'saving' | 'saved' | 'error'
  >('idle')
  const [draftSavedAt, setDraftSavedAt] = useState<Date | null>(null)
  const nodesRef = useRef(nodes)
  const edgesRef = useRef(edges)
  const dragSnapshotRef = useRef<WorkflowDefinition | null>(null)
  const lastAutosaveRef = useRef('')
  const importInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    nodesRef.current = nodes
  }, [nodes])

  useEffect(() => {
    edgesRef.current = edges
  }, [edges])

  useEffect(() => {
    if (catalog === undefined) return
    const nextNodes = toRfNodes(initialDefinition, catalog)
    const nextEdges = toRfEdges(initialDefinition)
    setNodes(nextNodes)
    setEdges(nextEdges)
    setSelectedId('')
    setHistory(emptyHistory())
    lastAutosaveRef.current = JSON.stringify(
      toDefinition(nextNodes, nextEdges),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed, catalog])

  const currentVersion = versions[0]?.version

  useEffect(() => {
    setTargetVersion(currentVersion ?? '')
  }, [currentVersion])

  useEffect(() => {
    if (onAutosave === undefined) return
    const definition = toDefinition(nodes, edges)
    const serialized = JSON.stringify(definition)
    if (serialized === lastAutosaveRef.current) return
    const timer = window.setTimeout(() => {
      setDraftState('saving')
      Promise.resolve(onAutosave(definition))
        .then(() => {
          lastAutosaveRef.current = serialized
          setDraftState('saved')
          setDraftSavedAt(new Date())
        })
        .catch(() => setDraftState('error'))
    }, 1200)
    return () => window.clearTimeout(timer)
  }, [nodes, edges, onAutosave])

  const selectedNode = nodes.find((node) => node.id === selectedId)
  const selectedMeta = catalog?.nodes.find(
    (item) => item.type === selectedNode?.data.nodeType,
  )
  const nodeOptions = useMemo(() => catalog?.nodes ?? [], [catalog])

  const currentDefinition = () =>
    toDefinition(nodesRef.current, edgesRef.current)

  const remember = () =>
    setHistory((previous) => recordHistory(previous, currentDefinition()))

  const applyDefinition = (definition: WorkflowDefinition) => {
    setNodes(
      toRfNodes(
        definition,
        catalog ?? {
          nodes: [],
          limits: { max_nodes: 30, max_kbs: 10 },
          variables: {},
        },
      ),
    )
    setEdges(toRfEdges(definition))
    setSelectedId('')
  }

  const undo = () => {
    const result = undoHistory(history, currentDefinition())
    if (result === null) return
    setHistory(result.history)
    applyDefinition(result.value)
  }

  const redo = () => {
    const result = redoHistory(history, currentDefinition())
    if (result === null) return
    setHistory(result.history)
    applyDefinition(result.value)
  }

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (
        target !== null &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable)
      ) {
        return
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) redo()
        else undo()
      } else if (
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === 'y'
      ) {
        event.preventDefault()
        redo()
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history, nodes, edges, catalog])

  const handleNodesChange = (changes: NodeChange<StudioNode>[]) => {
    if (changes.some((change) => change.type === 'remove')) remember()
    onNodesChange(changes)
  }

  const handleEdgesChange = (changes: EdgeChange<Edge>[]) => {
    if (changes.some((change) => change.type === 'remove')) remember()
    onEdgesChange(changes)
  }

  const addNode = (type: StudioNodeData['nodeType'], position?: { x: number; y: number }) => {
    remember()
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
    remember()
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
    remember()
    setNodes((prev) =>
      prev.map((node) =>
        node.id === selectedNode.id
          ? { ...node, data: { ...node.data, config } }
          : node,
      ),
    )
  }

  const updateEdgeWhen = (edgeId: string, when: 'true' | 'false') => {
    remember()
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
    remember()
    setNodes((prev) => prev.filter((node) => node.id !== selectedNode.id))
    setEdges((prev) =>
      prev.filter(
        (edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id,
      ),
    )
    setSelectedId('')
  }

  const exportDefinition = () => {
    const blob = new Blob([JSON.stringify(currentDefinition(), null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `workflow-${new Date().toISOString().slice(0, 10)}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const importDefinition = async (file: File) => {
    setImportError(null)
    try {
      const parsed = JSON.parse(await file.text()) as WorkflowDefinition
      if (
        !parsed ||
        !Array.isArray(parsed.nodes) ||
        !Array.isArray(parsed.edges)
      ) {
        throw new Error('invalid')
      }
      remember()
      applyDefinition(parsed)
    } catch {
      setImportError(t('studio.importInvalid'))
    }
  }

  const restoreVersion = async () => {
    if (onRestoreVersion === undefined || targetVersion === '') return
    setRestoring(true)
    try {
      await onRestoreVersion(Number(targetVersion))
    } finally {
      setRestoring(false)
    }
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
            onNodesChange={handleNodesChange}
            onEdgesChange={handleEdgesChange}
            onConnect={onConnect}
            onNodeDragStart={() => {
              dragSnapshotRef.current = currentDefinition()
            }}
            onNodeDragStop={() => {
              const before = dragSnapshotRef.current
              dragSnapshotRef.current = null
              if (before !== null) {
                setHistory((previous) => recordHistory(previous, before))
              }
            }}
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
        <div className="absolute bottom-4 left-4 z-10 flex max-w-[calc(100%-2rem)] flex-wrap items-center gap-2 rounded-lg border border-border bg-surface/95 p-2 backdrop-blur">
          <Button
            size="sm"
            disabled={saving}
            onClick={() => onSave(toDefinition(nodes, edges))}
          >
            <Save className="h-3.5 w-3.5" />
            {t('studio.saveCanvas')}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={history.past.length === 0}
            aria-label={t('studio.undo')}
            title={t('studio.undo')}
            onClick={undo}
          >
            <Undo2 className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={history.future.length === 0}
            aria-label={t('studio.redo')}
            title={t('studio.redo')}
            onClick={redo}
          >
            <Redo2 className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={t('studio.exportJson')}
            title={t('studio.exportJson')}
            onClick={exportDefinition}
          >
            <Download className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={t('studio.importJson')}
            title={t('studio.importJson')}
            onClick={() => importInputRef.current?.click()}
          >
            <Upload className="h-3.5 w-3.5" />
          </Button>
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file !== undefined) void importDefinition(file)
              event.target.value = ''
            }}
          />
          {versions.length > 0 && onRestoreVersion !== undefined && (
            <div className="flex items-center gap-1">
              <select
                value={targetVersion}
                onChange={(event) =>
                  setTargetVersion(
                    event.target.value === '' ? '' : Number(event.target.value),
                  )
                }
                className="h-8 rounded-lg border border-border bg-surface px-2 text-xs text-ink"
                aria-label={t('studio.versions')}
              >
                {versions.map((version) => (
                  <option key={version.id} value={version.version}>
                    v{version.version}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="secondary"
                disabled={
                  restoring ||
                  targetVersion === '' ||
                  targetVersion === currentVersion
                }
                onClick={() => void restoreVersion()}
              >
                {t('studio.restoreVersion')}
              </Button>
            </div>
          )}
          {draftState !== 'idle' && (
            <span
              className={`text-[11px] ${
                draftState === 'error' ? 'text-danger' : 'text-ink-muted'
              }`}
            >
              {draftState === 'saving' && t('studio.draftSaving')}
              {draftState === 'saved' &&
                t('studio.draftSaved', {
                  time: draftSavedAt?.toLocaleTimeString() ?? '',
                })}
              {draftState === 'error' && t('studio.draftError')}
            </span>
          )}
          {importError !== null && (
            <span className="text-[11px] text-danger">{importError}</span>
          )}
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
            workflowId={workflowId}
            version={version}
            debuggable={debuggable}
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
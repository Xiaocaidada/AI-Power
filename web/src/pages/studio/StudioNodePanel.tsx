import type { Edge, Node } from '@xyflow/react'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'

import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { MultiPopoverSelect } from '../../components/ui/multi-popover-select'
import { PopoverSelect } from '../../components/ui/popover-select'
import { useI18n } from '../../lib/i18n'
import type { WorkflowCatalogNode } from '../../lib/types'
import type { StudioNodeData, StudioResources } from './types'

interface JsonFieldProps {
  label: string
  value: unknown
  onChange: (value: unknown) => void
}

function JsonField({ label, value, onChange }: JsonFieldProps) {
  const [text, setText] = useState(() => JSON.stringify(value ?? {}, null, 2))
  const [invalid, setInvalid] = useState(false)
  return (
    <label className="block text-xs text-ink-muted">
      {label}
      <textarea
        value={text}
        onChange={(event) => {
          const next = event.target.value
          setText(next)
          try {
            const parsed = next.trim() === '' ? {} : JSON.parse(next)
            setInvalid(false)
            onChange(parsed)
          } catch {
            setInvalid(true)
          }
        }}
        className="mt-1 min-h-20 w-full rounded-lg border border-border bg-surface px-2 py-1.5 font-mono text-[11px] text-ink"
      />
      {invalid && <span className="text-[10px] text-danger">JSON invalid</span>}
    </label>
  )
}

interface StudioNodePanelProps {
  node: Node<StudioNodeData>
  meta: WorkflowCatalogNode | undefined
  edges: Edge[]
  resources: StudioResources
  onChange: (config: Record<string, unknown>) => void
  onEdgeWhen: (edgeId: string, when: 'true' | 'false') => void
  onRemove: () => void
}

export function StudioNodePanel({
  node,
  meta,
  edges,
  resources,
  onChange,
  onEdgeWhen,
  onRemove,
}: StudioNodePanelProps) {
  const { t } = useI18n()
  const config = node.data.config
  const set = (name: string, value: unknown) =>
    onChange({ ...config, [name]: value })

  const providers = Array.from(
    new Map(resources.models.map((item) => [item.provider_id, item.provider_id])).keys(),
  )
  const modelsForProvider = resources.models.filter(
    (item) =>
      config.provider_id === undefined ||
      config.provider_id === '' ||
      item.provider_id === config.provider_id,
  )

  return (
    <div className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-ink">{meta?.label ?? node.data.nodeType}</p>
          <p className="mt-0.5 text-[11px] text-ink-muted">{meta?.description}</p>
        </div>
        <Button variant="ghost" size="sm" aria-label={t('common.delete')} onClick={onRemove}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
      <p className="mt-2 font-mono text-[10px] text-ink-muted">{node.id}</p>

      <div className="mt-4 space-y-3">
        {(meta?.config_fields ?? []).map((field) => {
          const value = config[field.name]
          if (field.kind === 'textarea') {
            return (
              <label key={field.name} className="block text-xs text-ink-muted">
                {field.label}
                <textarea
                  value={typeof value === 'string' ? value : ''}
                  onChange={(event) => set(field.name, event.target.value)}
                  className="mt-1 min-h-24 w-full rounded-lg border border-border bg-surface px-2 py-1.5 font-mono text-[11px] text-ink"
                />
                {field.hint && (
                  <span className="text-[10px] text-ink-muted">{field.hint}</span>
                )}
              </label>
            )
          }
          if (field.kind === 'number') {
            return (
              <label key={field.name} className="block text-xs text-ink-muted">
                {field.label}
                <Input
                  className="mt-1"
                  type="number"
                  value={typeof value === 'number' ? value : ''}
                  onChange={(event) =>
                    set(
                      field.name,
                      event.target.value === '' ? undefined : Number(event.target.value),
                    )
                  }
                />
              </label>
            )
          }
          if (field.kind === 'select') {
            return (
              <div key={field.name} className="text-xs text-ink-muted">
                {field.label}
                <PopoverSelect
                  label={field.label}
                  value={typeof value === 'string' ? value : ''}
                  options={(field.options ?? []).map((option) => ({
                    value: option,
                    label: option,
                  }))}
                  onChange={(next) => set(field.name, next)}
                />
              </div>
            )
          }
          if (field.kind === 'json') {
            return (
              <JsonField
                key={`${node.id}-${field.name}`}
                label={field.label}
                value={value}
                onChange={(next) => set(field.name, next)}
              />
            )
          }
          if (field.kind === 'boolean') {
            return (
              <label
                key={field.name}
                className="flex items-center gap-2 text-xs text-ink"
              >
                <input
                  type="checkbox"
                  checked={value === true}
                  onChange={(event) => set(field.name, event.target.checked)}
                />
                {field.label}
              </label>
            )
          }
          if (field.kind === 'project') {
            return (
              <div key={field.name} className="text-xs text-ink-muted">
                {field.label}
                <PopoverSelect
                  label={field.label}
                  value={typeof value === 'string' ? value : ''}
                  options={[
                    { value: '', label: t('studio.noProject') },
                    ...resources.projects.map((project) => ({
                      value: project.id,
                      label: project.name,
                    })),
                  ]}
                  onChange={(next) => set(field.name, next === '' ? undefined : next)}
                />
              </div>
            )
          }
          if (field.kind === 'provider') {
            return (
              <div key={field.name} className="text-xs text-ink-muted">
                {field.label}
                <PopoverSelect
                  label={field.label}
                  value={typeof value === 'string' ? value : ''}
                  options={providers.map((provider) => ({
                    value: provider,
                    label: provider,
                  }))}
                  onChange={(next) => {
                    onChange({ ...config, provider_id: next, model: '' })
                  }}
                />
              </div>
            )
          }
          if (field.kind === 'model') {
            return (
              <div key={field.name} className="text-xs text-ink-muted">
                {field.label}
                <PopoverSelect
                  label={field.label}
                  value={typeof value === 'string' ? value : ''}
                  options={modelsForProvider.map((choice) => ({
                    value: choice.model,
                    label: choice.label,
                    description: choice.provider_id,
                  }))}
                  onChange={(next) => set(field.name, next)}
                />
              </div>
            )
          }
          if (field.kind === 'agent') {
            return (
              <div key={field.name} className="text-xs text-ink-muted">
                {field.label}
                <PopoverSelect
                  label={field.label}
                  value={typeof value === 'string' ? value : ''}
                  options={[
                    { value: '', label: t('studio.noAgent') },
                    ...resources.agents.map((agent) => ({
                      value: agent.id,
                      label: agent.name,
                    })),
                  ]}
                  onChange={(next) => set(field.name, next === '' ? undefined : next)}
                />
              </div>
            )
          }
          if (field.kind === 'db_connection') {
            return (
              <div key={field.name} className="text-xs text-ink-muted">
                {field.label}
                <PopoverSelect
                  label={field.label}
                  value={typeof value === 'string' ? value : ''}
                  options={[
                    { value: '', label: t('studio.noDatabase') },
                    ...resources.databaseConnections.map((connection) => ({
                      value: connection.id,
                      label: connection.name,
                      description: connection.description,
                    })),
                  ]}
                  onChange={(next) => set(field.name, next === '' ? undefined : next)}
                />
              </div>
            )
          }
          if (field.kind === 'mcp_server') {
            return (
              <div key={field.name} className="text-xs text-ink-muted">
                {field.label}
                <PopoverSelect
                  label={field.label}
                  value={typeof value === 'string' ? value : ''}
                  options={[
                    { value: '', label: t('studio.noMcpServer') },
                    ...resources.mcpServers.map((server) => ({
                      value: server.id,
                      label: server.name,
                      description: server.description,
                    })),
                  ]}
                  onChange={(next) => set(field.name, next === '' ? undefined : next)}
                />
              </div>
            )
          }
          if (field.kind === 'kb_multi') {
            const selected = Array.isArray(value) ? value.map(String) : []
            return (
              <div key={field.name}>
                <MultiPopoverSelect
                  label={field.label}
                  values={selected}
                  options={resources.knowledgeBases.map((kb) => ({
                    value: kb.id,
                    label: kb.name,
                  }))}
                  onChange={(next) => set(field.name, next)}
                  placeholder={t('studio.noKnowledgeBases')}
                />
              </div>
            )
          }
          return (
            <label key={field.name} className="block text-xs text-ink-muted">
              {field.label}
              <Input
                className="mt-1"
                value={typeof value === 'string' ? value : ''}
                onChange={(event) => set(field.name, event.target.value)}
              />
            </label>
          )
        })}
      </div>

      {node.data.nodeType === 'condition' && (
        <div className="mt-4 border-t border-border pt-3">
          <p className="text-xs font-medium text-ink">{t('studio.conditionBranches')}</p>
          <div className="mt-2 space-y-2">
            {edges.map((edge) => (
              <div key={edge.id} className="flex items-center gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate text-ink-muted">{edge.target}</span>
                <PopoverSelect
                  label="when"
                  value={typeof edge.data?.when === 'string' ? edge.data.when : 'true'}
                  options={[
                    { value: 'true', label: 'true' },
                    { value: 'false', label: 'false' },
                  ]}
                  onChange={(next) => onEdgeWhen(edge.id, next as 'true' | 'false')}
                />
              </div>
            ))}
            {edges.length < 2 && (
              <p className="text-[10px] text-warning">{t('studio.conditionNeedsTwo')}</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
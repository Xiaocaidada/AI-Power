import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, RotateCcw } from 'lucide-react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { AgentMemory, MemoryRelation, MemoryVersion } from '../../lib/types'

interface MemoryDetailDialogProps {
  memory: AgentMemory | null
  onClose: () => void
  onEdit: (memory: AgentMemory) => void
  onChanged: () => void
}

export function MemoryDetailDialog({
  memory,
  onClose,
  onEdit,
  onChanged,
}: MemoryDetailDialogProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const memoryId = memory?.id ?? ''
  const versions = useQuery({
    queryKey: ['memory-versions', memoryId],
    queryFn: () => apiRequest<MemoryVersion[]>(`/memories/${memoryId}/versions`),
    enabled: memoryId !== '',
  })
  const relations = useQuery({
    queryKey: ['memory-relations', memoryId],
    queryFn: () => apiRequest<MemoryRelation[]>(`/memories/${memoryId}/relations`),
    enabled: memoryId !== '',
  })

  if (memory === null) return null

  const restore = async (version: number) => {
    try {
      await apiRequest(`/memories/${memory.id}/versions/${version}/restore`, {
        method: 'POST',
      })
      await queryClient.invalidateQueries({ queryKey: ['memories'] })
      await queryClient.invalidateQueries({ queryKey: ['memory-stats'] })
      await queryClient.invalidateQueries({
        queryKey: ['memory-versions', memoryId],
      })
      onChanged()
    } catch (caught) {
      window.alert(t(errorTextKey(caught)))
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={memory.title || t('memory.detailTitle')}
      className="max-w-3xl"
      footer={
        <>
          <Button size="sm" variant="secondary" onClick={onClose}>
            {t('common.close')}
          </Button>
          <Button size="sm" onClick={() => onEdit(memory)}>
            <Pencil className="h-3.5 w-3.5" />
            {t('common.edit')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="accent">{t(`memory.category.${memory.category}`)}</Badge>
          <Badge tone="neutral">{t(`memory.scopeType.${memory.scope_type}`)}</Badge>
          <Badge
            tone={
              memory.status === 'active'
                ? 'success'
                : memory.status === 'conflict'
                  ? 'danger'
                  : 'neutral'
            }
          >
            {t(`memory.status.${memory.status}`)}
          </Badge>
          {memory.pinned && <Badge tone="warning">{t('memory.pinned')}</Badge>}
          {memory.favorite && <Badge tone="warning">{t('memory.favorite')}</Badge>}
          {!memory.enabled && <Badge tone="danger">{t('memory.disabled')}</Badge>}
          <span className="text-[11px] text-ink-muted">
            v{memory.version} · {t('memory.useCount', { count: memory.use_count })}
          </span>
        </div>

        <p className="whitespace-pre-wrap rounded-lg bg-surface-muted p-3 text-sm text-ink">
          {memory.content}
        </p>

        <div className="grid gap-2 text-xs text-ink-muted sm:grid-cols-2">
          <span>
            {t('memory.source')}: {memory.source_type}
            {memory.source_id ? ` · ${memory.source_id}` : ''}
          </span>
          <span>
            {t('memory.updatedAt')}: {new Date(memory.updated_at).toLocaleString()}
          </span>
          <span>
            {t('memory.confidence')}: {(memory.confidence * 100).toFixed(0)}%
          </span>
          <span>
            {t('memory.validUntil')}:{' '}
            {memory.valid_until
              ? new Date(memory.valid_until).toLocaleDateString()
              : '—'}
          </span>
        </div>

        {memory.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {memory.tags.map((tag) => (
              <Badge key={tag} tone="neutral">
                {tag}
              </Badge>
            ))}
          </div>
        )}

        <section>
          <h3 className="text-xs font-medium text-ink">
            {t('memory.relations.title')}
          </h3>
          {relations.isLoading ? (
            <Spinner className="mt-2" />
          ) : (relations.data ?? []).length === 0 ? (
            <p className="mt-1 text-[11px] text-ink-muted">
              {t('memory.relations.empty')}
            </p>
          ) : (
            <ul className="mt-1 space-y-1">
              {(relations.data ?? []).map((relation) => (
                <li
                  key={relation.id}
                  className="rounded-md bg-surface-muted px-2 py-1 text-[11px] text-ink-muted"
                >
                  {relation.relation_type} → {relation.to_type} ·{' '}
                  {relation.to_id.slice(0, 8)}
                  {relation.basis !== '' ? ` · ${relation.basis}` : ''}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h3 className="text-xs font-medium text-ink">
            {t('memory.versions.title')}
          </h3>
          {versions.isLoading ? (
            <Spinner className="mt-2" />
          ) : (
            <ul className="mt-1 space-y-1">
              {(versions.data ?? []).map((version) => (
                <li
                  key={version.id}
                  className="flex flex-wrap items-center gap-2 rounded-md bg-surface-muted px-2 py-1 text-[11px]"
                >
                  <span className="font-mono text-ink">v{version.version}</span>
                  <span className="text-ink-muted">{version.change_reason}</span>
                  <span className="text-ink-muted">
                    {new Date(version.created_at).toLocaleString()}
                  </span>
                  {version.version !== memory.version && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="ml-auto"
                      onClick={() => void restore(version.version)}
                    >
                      <RotateCcw className="h-3 w-3" />
                      {t('memory.versions.restore')}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </Dialog>
  )
}
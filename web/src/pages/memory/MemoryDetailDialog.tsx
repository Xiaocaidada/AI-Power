import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  GitCompare,
  Pencil,
  Plus,
  RotateCcw,
  ThumbsDown,
  ThumbsUp,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  AgentMemory,
  MemoryFeedback,
  MemoryRelation,
  MemoryVersion,
  MemoryVersionDiff,
} from '../../lib/types'

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
  const [targetId, setTargetId] = useState('')
  const [relationType, setRelationType] = useState('related')
  const [basis, setBasis] = useState('')
  const [savingRelation, setSavingRelation] = useState(false)
  const [editingRelationId, setEditingRelationId] = useState('')
  const [editRelationType, setEditRelationType] = useState('related')
  const [editRelationBasis, setEditRelationBasis] = useState('')
  const [diffVersion, setDiffVersion] = useState<number | null>(null)
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
  const feedback = useQuery({
    queryKey: ['memory-feedback', memoryId],
    queryFn: () => apiRequest<MemoryFeedback>(`/memories/${memoryId}/feedback`),
    enabled: memoryId !== '',
  })
  const targets = useQuery({
    queryKey: ['memories', 'relation-targets'],
    queryFn: () => apiRequest<AgentMemory[]>('/memories?status=active&limit=100'),
    enabled: memoryId !== '',
  })
  const versionDiff = useQuery({
    queryKey: ['memory-diff', memoryId, diffVersion],
    queryFn: () =>
      apiRequest<MemoryVersionDiff>(
        `/memories/${memoryId}/versions/diff?to_version=${diffVersion}`,
      ),
    enabled: memoryId !== '' && diffVersion !== null,
    retry: false,
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

  const addRelation = async () => {
    if (targetId === '') return
    setSavingRelation(true)
    try {
      await apiRequest(`/memories/${memory.id}/relations`, {
        method: 'POST',
        body: {
          to_type: 'memory',
          to_id: targetId,
          relation_type: relationType,
          basis: basis.trim(),
        },
      })
      setTargetId('')
      setBasis('')
      await queryClient.invalidateQueries({
        queryKey: ['memory-relations', memoryId],
      })
      await queryClient.invalidateQueries({ queryKey: ['memory-graph'] })
    } catch (caught) {
      window.alert(t(errorTextKey(caught)))
    } finally {
      setSavingRelation(false)
    }
  }

  const removeRelation = async (relationId: string) => {
    await apiRequest(`/memories/relations/${relationId}`, { method: 'DELETE' })
    await queryClient.invalidateQueries({
      queryKey: ['memory-relations', memoryId],
    })
    await queryClient.invalidateQueries({ queryKey: ['memory-graph'] })
  }

  const startRelationEdit = (relation: MemoryRelation) => {
    setEditingRelationId(relation.id)
    setEditRelationType(relation.relation_type)
    setEditRelationBasis(relation.basis)
  }

  const saveRelationEdit = async () => {
    if (editingRelationId === '') return
    try {
      await apiRequest(`/memories/relations/${editingRelationId}`, {
        method: 'PATCH',
        body: {
          relation_type: editRelationType,
          basis: editRelationBasis.trim(),
        },
      })
      setEditingRelationId('')
      await queryClient.invalidateQueries({
        queryKey: ['memory-relations', memoryId],
      })
      await queryClient.invalidateQueries({ queryKey: ['memory-graph'] })
    } catch (caught) {
      window.alert(t(errorTextKey(caught)))
    }
  }

  const rate = async (rating: 'helpful' | 'unhelpful') => {
    try {
      if (feedback.data?.rating === rating) {
        await apiRequest(`/memories/${memory.id}/feedback`, { method: 'DELETE' })
      } else {
        await apiRequest(`/memories/${memory.id}/feedback`, {
          method: 'PUT',
          body: { rating, context_type: 'manual' },
        })
      }
      await queryClient.invalidateQueries({
        queryKey: ['memory-feedback', memoryId],
      })
      await queryClient.invalidateQueries({ queryKey: ['memories'] })
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

        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2 text-xs">
          <span className="text-ink-muted">{t('memory.feedback.title')}</span>
          <span className="text-ink-muted">
            {t('memory.feedback.counts', {
              helpful: feedback.data?.helpful_count ?? 0,
              unhelpful: feedback.data?.unhelpful_count ?? 0,
            })}
          </span>
          <Button
            size="sm"
            variant={feedback.data?.rating === 'helpful' ? 'primary' : 'secondary'}
            onClick={() => void rate('helpful')}
          >
            <ThumbsUp className="h-3 w-3" />
            {t('memory.feedback.helpful')}
          </Button>
          <Button
            size="sm"
            variant={
              feedback.data?.rating === 'unhelpful' ? 'primary' : 'secondary'
            }
            onClick={() => void rate('unhelpful')}
          >
            <ThumbsDown className="h-3 w-3" />
            {t('memory.feedback.unhelpful')}
          </Button>
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
              {(relations.data ?? []).map((relation) => {
                const outgoing =
                  relation.from_type === 'memory' &&
                  relation.from_id === memory.id
                const otherType = outgoing ? relation.to_type : relation.from_type
                const otherId = outgoing ? relation.to_id : relation.from_id
                const otherLabel =
                  targets.data?.find((item) => item.id === otherId)?.title ||
                  otherId.slice(0, 8)
                return (
                  <li
                    key={relation.id}
                    className="flex flex-wrap items-center gap-1.5 rounded-md bg-surface-muted px-2 py-1 text-[11px] text-ink-muted"
                  >
                    {editingRelationId === relation.id ? (
                      <>
                        <select
                          value={editRelationType}
                          onChange={(event) =>
                            setEditRelationType(event.target.value)
                          }
                          className="h-7 rounded border border-border bg-surface px-1 text-ink"
                        >
                          {[
                            'related',
                            'supports',
                            'contradicts',
                            'supersedes',
                            'derived_from',
                          ].map((item) => (
                            <option key={item} value={item}>
                              {t(`memory.relationType.${item}`)}
                            </option>
                          ))}
                        </select>
                        <input
                          value={editRelationBasis}
                          onChange={(event) =>
                            setEditRelationBasis(event.target.value)
                          }
                          placeholder={t('memory.relations.basis')}
                          className="h-7 min-w-40 flex-1 rounded border border-border bg-surface px-2 text-ink"
                        />
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => void saveRelationEdit()}
                        >
                          {t('common.save')}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setEditingRelationId('')}
                        >
                          {t('common.cancel')}
                        </Button>
                      </>
                    ) : (
                      <>
                        <Badge
                          tone={relation.source === 'auto' ? 'neutral' : 'accent'}
                        >
                          {relation.source === 'auto'
                            ? t('memory.relations.auto')
                            : t('memory.relations.manual')}
                        </Badge>
                        <span className="text-ink">
                          {outgoing ? '→' : '←'}{' '}
                          {t(`memory.relationType.${relation.relation_type}`)}
                        </span>
                        <span>
                          {otherType} · {otherLabel}
                        </span>
                        {relation.basis !== '' && <span>· {relation.basis}</span>}
                        <Button
                          size="sm"
                          variant="ghost"
                          className="ml-auto"
                          aria-label={t('common.edit')}
                          onClick={() => startRelationEdit(relation)}
                        >
                          <Pencil className="h-3 w-3" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={t('common.delete')}
                          onClick={() => void removeRelation(relation.id)}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select
              value={targetId}
              onChange={(event) => setTargetId(event.target.value)}
              className="h-8 min-w-40 flex-1 rounded-lg border border-border bg-surface px-2 text-[11px] text-ink"
            >
              <option value="">{t('memory.relations.selectTarget')}</option>
              {(targets.data ?? [])
                .filter((item) => item.id !== memory.id)
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title || item.content.slice(0, 40)}
                  </option>
                ))}
            </select>
            <select
              value={relationType}
              onChange={(event) => setRelationType(event.target.value)}
              className="h-8 rounded-lg border border-border bg-surface px-2 text-[11px] text-ink"
            >
              {(
                [
                  'related',
                  'supports',
                  'contradicts',
                  'supersedes',
                  'derived_from',
                ] as const
              ).map((item) => (
                <option key={item} value={item}>
                  {t(`memory.relationType.${item}`)}
                </option>
              ))}
            </select>
            <input
              value={basis}
              onChange={(event) => setBasis(event.target.value)}
              placeholder={t('memory.relations.basis')}
              className="h-8 min-w-40 flex-1 rounded-lg border border-border bg-surface px-2 text-[11px] text-ink"
            />
            <Button
              size="sm"
              disabled={savingRelation || targetId === ''}
              onClick={() => void addRelation()}
            >
              <Plus className="h-3 w-3" />
              {t('memory.relations.add')}
            </Button>
          </div>
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
                  {version.version > 1 && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="ml-auto"
                      onClick={() => setDiffVersion(version.version)}
                    >
                      <GitCompare className="h-3 w-3" />
                      {t('memory.diff.compare')}
                    </Button>
                  )}
                  {version.version !== memory.version && (
                    <Button
                      size="sm"
                      variant="ghost"
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
          {diffVersion !== null && (
            <div className="mt-3 rounded-lg border border-border bg-surface-muted p-3">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-xs font-medium text-ink">
                  {t('memory.diff.title')} v{versionDiff.data?.from_version ?? '–'} → v
                  {versionDiff.data?.to_version ?? diffVersion}
                </p>
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto"
                  onClick={() => setDiffVersion(null)}
                >
                  {t('common.close')}
                </Button>
              </div>
              {versionDiff.isLoading && <Spinner className="mt-2" />}
              {versionDiff.isError && (
                <p className="mt-2 text-[11px] text-danger">
                  {t('memory.diff.loadError')}
                </p>
              )}
              {versionDiff.data !== undefined && (
                <div className="mt-2 space-y-2">
                  {versionDiff.data.risk_flags.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {versionDiff.data.risk_flags.map((flag) => (
                        <Badge key={flag} tone="warning">
                          {t(`memory.diff.risk.${flag}`)}
                        </Badge>
                      ))}
                    </div>
                  )}
                  {versionDiff.data.changes.length === 0 ? (
                    <p className="text-[11px] text-ink-muted">
                      {t('memory.diff.noChanges')}
                    </p>
                  ) : (
                    <ul className="space-y-1 text-[11px] text-ink-muted">
                      {versionDiff.data.changes.map((change) => (
                        <li key={change.field}>
                          <span className="font-mono text-ink">{change.field}</span>:{' '}
                          {JSON.stringify(change.before)} →{' '}
                          {JSON.stringify(change.after)}
                        </li>
                      ))}
                    </ul>
                  )}
                  {versionDiff.data.content_diff !== '' && (
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-surface p-2 text-[10px] text-ink">
                      {versionDiff.data.content_diff}
                    </pre>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </Dialog>
  )
}
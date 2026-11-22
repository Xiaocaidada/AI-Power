import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  FileText,
  FileUp,
  Layers,
  Loader2,
  RefreshCw,
  RotateCw,
  Search,
  Settings,
  Tags,
  Trash2,
} from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { EmptyState } from '../../components/ui/empty-state'
import { Spinner } from '../../components/ui/spinner'
import {
  documentErrorKey,
  documentIsProcessing,
  documentStatusKey,
  documentStatusTone,
  shouldPollDocuments,
} from '../../lib/documentMeta'
import { errorTextKey } from '../../lib/errorText'
import { formatBytes, formatDate } from '../../lib/format'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { PAGE_SIZE, mergePages, pageFromItems } from '../../lib/pagination'
import type {
  DocumentItem,
  KnowledgeBase,
  KnowledgeBaseSettings,
  KnowledgeBaseStats,
} from '../../lib/types'
import { uploadDocument } from '../../lib/upload'
import {
  createUploadTasks,
  type UploadTask,
} from '../../lib/uploadBatch'
import { KnowledgeChunksTab } from './KnowledgeChunksTab'
import { KnowledgeRetrievalTab } from './KnowledgeRetrievalTab'
import { KnowledgeSettingsTab } from './KnowledgeSettingsTab'

type TabId = 'documents' | 'chunks' | 'retrieval' | 'settings'

export function KnowledgeDetailPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { t, language } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement | null>(null)
  const [tab, setTab] = useState<TabId>('documents')
  const [uploads, setUploads] = useState<UploadTask[]>([])
  const [actionError, setActionError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null)
  const [docQuery, setDocQuery] = useState('')
  const [docTag, setDocTag] = useState('')
  const [tagTarget, setTagTarget] = useState<DocumentItem | null>(null)
  const [tagDraft, setTagDraft] = useState('')
  const [reprocessTarget, setReprocessTarget] = useState<DocumentItem | null>(null)

  const kb = useQuery({
    queryKey: ['kb', id],
    queryFn: () => apiRequest<KnowledgeBase>(`/knowledge-bases/${id}`),
    enabled: id !== '',
  })
  const settings = useQuery({
    queryKey: ['kb-settings', id],
    queryFn: () => apiRequest<KnowledgeBaseSettings>(`/knowledge-bases/${id}/settings`),
    enabled: id !== '',
  })
  const stats = useQuery({
    queryKey: ['kb-stats', id],
    queryFn: () => apiRequest<KnowledgeBaseStats>(`/knowledge-bases/${id}/stats`),
    enabled: id !== '',
    refetchInterval: (query) => (query.state.data?.processing_count ? 2000 : false),
  })
  const documents = useInfiniteQuery({
    queryKey: ['documents', id, docQuery, docTag],
    queryFn: async ({ pageParam }) => {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE) })
      if (pageParam) params.set('before', pageParam)
      if (docQuery.trim()) params.set('q', docQuery.trim())
      if (docTag.trim()) params.set('tag', docTag.trim())
      return pageFromItems(
        await apiRequest<DocumentItem[]>(
          `/knowledge-bases/${id}/documents?${params.toString()}`,
        ),
        PAGE_SIZE,
      )
    },
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next,
    enabled: id !== '',
    refetchInterval: (query) =>
      shouldPollDocuments(mergePages(query.state.data?.pages)) ? 2000 : false,
  })

  const refreshKnowledgeBase = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['documents', id] }),
      queryClient.invalidateQueries({ queryKey: ['kb-chunks', id] }),
      queryClient.invalidateQueries({ queryKey: ['kb-stats', id] }),
    ])
  }

  const updateUpload = (taskId: string, patch: Partial<UploadTask>) => {
    setUploads((previous) =>
      previous.map((task) => (task.id === taskId ? { ...task, ...patch } : task)),
    )
  }

  const uploadBatch = async (files: File[]) => {
    if (files.length === 0) return
    const tasks = createUploadTasks(files)
    setUploads((previous) => [
      ...previous.filter((task) => task.status === 'uploading'),
      ...tasks,
    ])
    let changed = false
    for (const [index, task] of tasks.entries()) {
      if (task.status !== 'uploading') continue
      try {
        const result = await uploadDocument({
          kbId: id,
          file: files[index],
          onProgress: (percent) => updateUpload(task.id, { percent }),
        })
        updateUpload(task.id, {
          percent: 100,
          status: result.duplicate ? 'duplicate' : 'ready',
        })
        changed = true
      } catch (caught) {
        updateUpload(task.id, {
          status: 'failed',
          errorKey: errorTextKey(caught),
        })
      }
    }
    if (changed) await refreshKnowledgeBase()
  }

  const retry = async (documentId: string) => {
    setActionError(null)
    try {
      await apiRequest(`/documents/${documentId}/retry`, { method: 'POST' })
      await refreshKnowledgeBase()
    } catch (caught) {
      setActionError(t(errorTextKey(caught)))
    }
  }

  const reprocess = async () => {
    if (reprocessTarget === null) return
    setActionError(null)
    try {
      await apiRequest(`/documents/${reprocessTarget.id}/reprocess`, { method: 'POST' })
      await refreshKnowledgeBase()
    } catch (caught) {
      setActionError(t(errorTextKey(caught)))
    } finally {
      setReprocessTarget(null)
    }
  }

  const remove = async () => {
    if (deleteTarget === null) return
    try {
      await apiRequest(`/documents/${deleteTarget.id}`, { method: 'DELETE' })
      await refreshKnowledgeBase()
    } catch (caught) {
      setActionError(t(errorTextKey(caught)))
    } finally {
      setDeleteTarget(null)
    }
  }

  const saveTags = async () => {
    if (tagTarget === null) return
    const tags = tagDraft
      .split(',')
      .map((item) => item.trim())
      .filter((item) => item !== '')
    setActionError(null)
    try {
      await apiRequest(`/documents/${tagTarget.id}`, {
        method: 'PATCH',
        body: { tags },
      })
      await refreshKnowledgeBase()
      setTagTarget(null)
    } catch (caught) {
      setActionError(t(errorTextKey(caught)))
    }
  }

  if (kb.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner className="h-6 w-6 text-accent" />
      </div>
    )
  }

  if (kb.isError || kb.data === undefined) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <p className="text-sm text-ink-muted">{t('errors.notFound')}</p>
        <Button variant="secondary" onClick={() => navigate('/knowledge')}>
          {t('knowledge.back')}
        </Button>
      </div>
    )
  }

  const rows = mergePages(documents.data?.pages)
  const tabs: { id: TabId; label: string; icon: typeof FileText }[] = [
    { id: 'documents', label: t('knowledge.tabs.documents'), icon: FileText },
    { id: 'chunks', label: t('knowledge.tabs.chunks'), icon: Layers },
    { id: 'retrieval', label: t('knowledge.tabs.retrieval'), icon: Search },
    { id: 'settings', label: t('knowledge.tabs.settings'), icon: Settings },
  ]

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <button
          type="button"
          className="mb-2 inline-flex items-center gap-1 text-xs text-ink-muted hover:text-ink"
          onClick={() => navigate('/knowledge')}
        >
          <ArrowLeft className="h-3 w-3" />
          {t('knowledge.back')}
        </button>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">{kb.data.name}</h1>
            <p className="mt-1 text-xs text-ink-muted">
              {t('knowledge.created', { date: formatDate(kb.data.created_at, language) })}
              {rows.length > 0 ? ` · ${t('documents.count', { count: rows.length })}` : ''}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
            <span className="rounded-full bg-surface-muted px-2 py-1">
              {t('knowledge.stats.documents', { count: stats.data?.document_count ?? 0 })}
            </span>
            <span className="rounded-full bg-surface-muted px-2 py-1">
              {t('knowledge.stats.chunks', { count: stats.data?.chunk_count ?? 0 })}
            </span>
            <span className="rounded-full bg-surface-muted px-2 py-1">
              {t('knowledge.stats.chars', { count: stats.data?.char_count ?? 0 })}
            </span>
            <Button onClick={() => fileInput.current?.click()}>
              <FileUp className="h-4 w-4" />
              {t('documents.upload')}
            </Button>
          </div>
        </div>
      </header>

      <nav className="flex gap-1 border-b border-border bg-surface px-6">
        {tabs.map(({ id: tabId, label, icon: Icon }) => (
          <button
            key={tabId}
            type="button"
            className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm transition-colors ${
              tab === tabId
                ? 'border-accent text-accent'
                : 'border-transparent text-ink-muted hover:text-ink'
            }`}
            onClick={() => setTab(tabId)}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </nav>

      <div className="space-y-4 px-6 py-6">
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.md,.txt"
          multiple
          className="hidden"
          onChange={(event) => {
            void uploadBatch(Array.from(event.target.files ?? []))
            event.target.value = ''
          }}
        />

        {actionError !== null && (
          <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {actionError}
          </p>
        )}

        {tab === 'documents' && (
          <>
            <div
              role="button"
              tabIndex={0}
              className="rounded-card border border-dashed border-border bg-surface px-6 py-8 text-center transition-colors hover:border-accent/50 focus:border-accent"
              onClick={() => fileInput.current?.click()}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') fileInput.current?.click()
              }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                void uploadBatch(Array.from(event.dataTransfer.files))
              }}
            >
              <FileUp className="mx-auto h-6 w-6 text-ink-muted" />
              <p className="mt-2 text-sm text-ink">{t('documents.dropzone')}</p>
              <p className="mt-1 text-xs text-ink-muted">{t('documents.types')}</p>
            </div>

            <div className="flex flex-wrap gap-2">
              <input
                value={docQuery}
                onChange={(event) => setDocQuery(event.target.value)}
                placeholder={t('documents.search')}
                className="h-9 w-full max-w-xs rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
              />
              <input
                value={docTag}
                onChange={(event) => setDocTag(event.target.value)}
                placeholder={t('documents.tagFilter')}
                className="h-9 w-40 rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
              />
            </div>

            {uploads.length > 0 && (
              <section className="rounded-card border border-border bg-surface p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-medium">{t('documents.batchTitle')}</h3>
                  {!uploads.some((task) => task.status === 'uploading') && (
                    <Button variant="ghost" size="sm" onClick={() => setUploads([])}>
                      {t('documents.batchClear')}
                    </Button>
                  )}
                </div>
                <ul className="mt-2 space-y-2">
                  {uploads.map((task) => (
                    <li key={task.id} className="rounded-lg border border-border px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="min-w-0 flex-1 truncate font-mono text-ink">
                          {task.name}
                        </span>
                        {task.status === 'uploading' && (
                          <span className="text-ink-muted">
                            {t('documents.uploadProgress', { percent: task.percent })}
                          </span>
                        )}
                        {task.status === 'ready' && (
                          <span className="text-success">{t('documents.uploaded')}</span>
                        )}
                        {task.status === 'duplicate' && (
                          <span className="text-warning">{t('documents.duplicateShort')}</span>
                        )}
                        {task.status === 'failed' && (
                          <span className="text-danger">
                            {t(task.errorKey ?? 'documents.uploadFailed')}
                          </span>
                        )}
                      </div>
                      {task.status === 'uploading' && (
                        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-muted">
                          <div
                            className="h-full bg-accent transition-all"
                            style={{ width: `${task.percent}%` }}
                          />
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {documents.isLoading && (
              <div className="flex items-center gap-2 text-sm text-ink-muted">
                <Spinner />
                {t('common.loading')}
              </div>
            )}

            {!documents.isLoading && rows.length === 0 && (
              <EmptyState title={t('documents.empty')} description={t('documents.emptyLead')} />
            )}

            {rows.length > 0 && (
              <div className="overflow-x-auto rounded-card border border-border bg-surface">
                <table className="w-full min-w-[760px] text-left text-sm">
                  <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                    <tr>
                      <th className="px-3 py-2 font-medium">{t('documents.columns.filename')}</th>
                      <th className="px-3 py-2 font-medium">{t('documents.columns.status')}</th>
                      <th className="px-3 py-2 font-medium">{t('documents.columns.size')}</th>
                      <th className="px-3 py-2 font-medium">{t('documents.columns.pages')}</th>
                      <th className="px-3 py-2 font-medium">{t('documents.columns.tags')}</th>
                      <th className="px-3 py-2 font-medium">{t('documents.columns.error')}</th>
                      <th className="px-3 py-2 text-right font-medium">
                        {t('documents.columns.actions')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((document) => (
                      <tr key={document.id} className="border-b border-border last:border-0">
                        <td className="px-3 py-3">
                          <span className="block max-w-[280px] truncate font-medium text-ink">
                            {document.filename}
                          </span>
                          <span className="text-xs text-ink-muted">
                            {formatDate(document.created_at, language)}
                          </span>
                        </td>
                        <td className="px-3 py-3">
                          <Badge tone={documentStatusTone(document.status)}>
                            {documentIsProcessing(document.status) && (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            )}
                            {t(documentStatusKey(document.status))}
                          </Badge>
                        </td>
                        <td className="px-3 py-3 font-mono text-xs text-ink-muted">
                          {formatBytes(document.size_bytes)}
                        </td>
                        <td className="px-3 py-3 text-ink-muted">{document.page_count ?? '—'}</td>
                        <td className="px-3 py-3">
                          <div className="flex flex-wrap gap-1">
                            {(document.tags ?? []).map((tag) => (
                              <Badge key={tag} tone="neutral">
                                {tag}
                              </Badge>
                            ))}
                          </div>
                        </td>
                        <td className="px-3 py-3 text-xs text-danger">
                          {document.error_code !== null
                            ? t(documentErrorKey(document.error_code), {
                                code: document.error_code,
                              })
                            : '—'}
                        </td>
                        <td className="px-3 py-3">
                          <div className="flex justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={t('documents.editTags')}
                              title={t('documents.editTags')}
                              onClick={() => {
                                setTagTarget(document)
                                setTagDraft((document.tags ?? []).join(', '))
                              }}
                            >
                              <Tags className="h-4 w-4" />
                            </Button>
                            {document.status === 'failed' && (
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={() => void retry(document.id)}
                              >
                                <RotateCw className="h-3 w-3" />
                                {t('documents.retry')}
                              </Button>
                            )}
                            {!documentIsProcessing(document.status) && (
                              <Button
                                variant="secondary"
                                size="sm"
                                title={t('documents.reprocessHint')}
                                onClick={() => setReprocessTarget(document)}
                              >
                                <RefreshCw className="h-3 w-3" />
                                {t('documents.reprocess')}
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={t('documents.delete')}
                              onClick={() => setDeleteTarget(document)}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {documents.hasNextPage && (
              <div className="flex justify-center">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={documents.isFetchingNextPage}
                  onClick={() => void documents.fetchNextPage()}
                >
                  {documents.isFetchingNextPage ? t('common.loading') : t('common.loadMore')}
                </Button>
              </div>
            )}
          </>
        )}

        {tab === 'chunks' && <KnowledgeChunksTab kbId={id} documents={rows} />}

        {tab === 'retrieval' && <KnowledgeRetrievalTab kbId={id} settings={settings.data} />}

        {tab === 'settings' &&
          (settings.data === undefined ? (
            <div className="flex items-center gap-2 text-sm text-ink-muted">
              <Spinner />
              {t('common.loading')}
            </div>
          ) : (
            <KnowledgeSettingsTab
              kbId={id}
              settings={settings.data}
              onSaved={(saved) => queryClient.setQueryData(['kb-settings', id], saved)}
            />
          ))}
      </div>

      <Dialog
        open={tagTarget !== null}
        onClose={() => setTagTarget(null)}
        title={t('documents.editTags')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setTagTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" onClick={() => void saveTags()}>
              {t('common.save')}
            </Button>
          </>
        }
      >
        <p className="mb-2 text-xs text-ink-muted">{t('documents.tagHint')}</p>
        <input
          value={tagDraft}
          onChange={(event) => setTagDraft(event.target.value)}
          placeholder={t('documents.tagPlaceholder')}
          className="h-9 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
        />
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title={t('documents.delete')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDeleteTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" size="sm" onClick={() => void remove()}>
              {t('common.confirm')}
            </Button>
          </>
        }
      >
        <p>{t('documents.deleteConfirm')}</p>
      </Dialog>

      <Dialog
        open={reprocessTarget !== null}
        onClose={() => setReprocessTarget(null)}
        title={t('documents.reprocess')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setReprocessTarget(null)}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" onClick={() => void reprocess()}>
              {t('common.confirm')}
            </Button>
          </>
        }
      >
        <p>{t('documents.reprocessConfirm')}</p>
        <p className="mt-2 text-xs text-ink-muted">{t('documents.reprocessHint')}</p>
      </Dialog>
    </div>
  )
}
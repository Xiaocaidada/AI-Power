import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, FileUp, Loader2, RotateCw, Trash2 } from 'lucide-react'
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
import type { DocumentItem, KnowledgeBase } from '../../lib/types'
import { uploadDocument } from '../../lib/upload'

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['.pdf', '.md', '.txt']

export function KnowledgeDetailPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { t, language } = useI18n()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement | null>(null)
  const [uploading, setUploading] = useState<{ name: string; percent: number } | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null)

  const kb = useQuery({
    queryKey: ['kb', id],
    queryFn: () => apiRequest<KnowledgeBase>(`/knowledge-bases/${id}`),
    enabled: id !== '',
  })
  const documents = useInfiniteQuery({
    queryKey: ['documents', id],
    queryFn: async ({ pageParam }) =>
      pageFromItems(
        await apiRequest<DocumentItem[]>(
          `/knowledge-bases/${id}/documents?limit=${PAGE_SIZE}${
            pageParam ? `&before=${pageParam}` : ''
          }`,
        ),
        PAGE_SIZE,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next,
    enabled: id !== '',
    refetchInterval: (query) =>
      shouldPollDocuments(mergePages(query.state.data?.pages)) ? 2000 : false,
  })

  const upload = async (file: File) => {
    const suffix = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    if (!ALLOWED_EXTENSIONS.includes(suffix)) {
      setUploadError(t('errors.unsupportedType'))
      return
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploadError(t('errors.tooLarge'))
      return
    }
    setUploadError(null)
    setUploading({ name: file.name, percent: 0 })
    try {
      const result = await uploadDocument({
        kbId: id,
        file,
        onProgress: (percent) =>
          setUploading((previous) => (previous === null ? previous : { ...previous, percent })),
      })
      if (result.duplicate) setUploadError(t('documents.duplicate'))
      await queryClient.invalidateQueries({ queryKey: ['documents', id] })
    } catch (caught) {
      setUploadError(t(errorTextKey(caught)))
    } finally {
      setUploading(null)
    }
  }

  const retry = async (documentId: string) => {
    setActionError(null)
    try {
      await apiRequest(`/documents/${documentId}/retry`, { method: 'POST' })
      await queryClient.invalidateQueries({ queryKey: ['documents', id] })
    } catch (caught) {
      setActionError(t(errorTextKey(caught)))
    }
  }

  const remove = async () => {
    if (deleteTarget === null) return
    try {
      await apiRequest(`/documents/${deleteTarget.id}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['documents', id] })
    } catch (caught) {
      setActionError(t(errorTextKey(caught)))
    } finally {
      setDeleteTarget(null)
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
          <Button onClick={() => fileInput.current?.click()}>
            <FileUp className="h-4 w-4" />
            {t('documents.upload')}
          </Button>
        </div>
      </header>

      <div className="space-y-4 px-6 py-6">
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.md,.txt"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file !== undefined) void upload(file)
            event.target.value = ''
          }}
        />

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
            const file = event.dataTransfer.files[0]
            if (file !== undefined) void upload(file)
          }}
        >
          <FileUp className="mx-auto h-6 w-6 text-ink-muted" />
          <p className="mt-2 text-sm text-ink">{t('documents.dropzone')}</p>
          <p className="mt-1 text-xs text-ink-muted">{t('documents.types')}</p>
        </div>

        {uploading !== null && (
          <div className="rounded-lg border border-border bg-surface p-3">
            <p className="text-xs text-ink-muted">
              {t('documents.uploading', { name: uploading.name, percent: uploading.percent })}
            </p>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-muted">
              <div
                className="h-full bg-accent transition-all"
                style={{ width: `${uploading.percent}%` }}
              />
            </div>
          </div>
        )}

        {uploadError !== null && (
          <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {uploadError}
          </p>
        )}
        {actionError !== null && (
          <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
            {actionError}
          </p>
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
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">{t('documents.columns.filename')}</th>
                  <th className="px-3 py-2 font-medium">{t('documents.columns.status')}</th>
                  <th className="px-3 py-2 font-medium">{t('documents.columns.size')}</th>
                  <th className="px-3 py-2 font-medium">{t('documents.columns.pages')}</th>
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
                    <td className="px-3 py-3 text-xs text-danger">
                      {document.error_code !== null
                        ? t(documentErrorKey(document.error_code), { code: document.error_code })
                        : '—'}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex justify-end gap-1">
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
      </div>

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
    </div>
  )
}
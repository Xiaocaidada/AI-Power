import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Search } from 'lucide-react'
import { useState } from 'react'

import { Button } from '../../components/ui/button'
import { EmptyState } from '../../components/ui/empty-state'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { ChunkPage, DocumentItem } from '../../lib/types'

const PAGE_SIZE = 10

interface KnowledgeChunksTabProps {
  kbId: string
  documents: DocumentItem[]
}

export function KnowledgeChunksTab({ kbId, documents }: KnowledgeChunksTabProps) {
  const { t } = useI18n()
  const [documentId, setDocumentId] = useState('')
  const [search, setSearch] = useState('')
  const [appliedQuery, setAppliedQuery] = useState('')
  const [offset, setOffset] = useState(0)

  const chunks = useQuery({
    queryKey: ['kb-chunks', kbId, documentId, appliedQuery, offset],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) })
      if (documentId !== '') params.set('document_id', documentId)
      if (appliedQuery !== '') params.set('q', appliedQuery)
      return apiRequest<ChunkPage>(`/knowledge-bases/${kbId}/chunks?${params.toString()}`)
    },
  })

  const total = chunks.data?.total ?? 0
  const start = total === 0 ? 0 : offset + 1
  const end = Math.min(offset + PAGE_SIZE, total)

  const submitSearch = () => {
    setOffset(0)
    setAppliedQuery(search.trim())
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2 rounded-card border border-border bg-surface p-3">
        <label className="min-w-[220px] flex-1 text-xs text-ink-muted">
          <span className="mb-1 block">{t('knowledge.chunks.filterDocument')}</span>
          <select
            className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm text-ink focus:border-accent focus:outline-none"
            value={documentId}
            onChange={(event) => {
              setDocumentId(event.target.value)
              setOffset(0)
            }}
          >
            <option value="">{t('knowledge.chunks.allDocuments')}</option>
            {documents.map((document) => (
              <option key={document.id} value={document.id}>
                {document.filename}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-[240px] flex-[2] text-xs text-ink-muted">
          <span className="mb-1 block">{t('knowledge.chunks.search')}</span>
          <div className="flex gap-2">
            <Input
              value={search}
              maxLength={200}
              placeholder={t('knowledge.chunks.searchPlaceholder')}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') submitSearch()
              }}
            />
            <Button variant="secondary" onClick={submitSearch}>
              <Search className="h-4 w-4" />
              {t('knowledge.chunks.searchAction')}
            </Button>
          </div>
        </label>
      </div>

      {chunks.isLoading && (
        <div className="flex items-center gap-2 text-sm text-ink-muted">
          <Spinner />
          {t('common.loading')}
        </div>
      )}

      {chunks.isError && (
        <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
          {t(errorTextKey(chunks.error))}
        </p>
      )}

      {!chunks.isLoading && chunks.isSuccess && total === 0 && (
        <EmptyState
          title={t('knowledge.chunks.empty')}
          description={t('knowledge.chunks.emptyLead')}
        />
      )}

      {total > 0 && (
        <>
          <div className="flex items-center justify-between text-xs text-ink-muted">
            <span>{t('knowledge.chunks.range', { start, end, total })}</span>
            <span>{t('knowledge.chunks.pageSize', { count: PAGE_SIZE })}</span>
          </div>
          <div className="space-y-3">
            {chunks.data?.items.map((chunk) => (
              <article
                key={chunk.id}
                className="rounded-card border border-border bg-surface p-4"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
                  <span className="font-medium text-ink">{chunk.filename}</span>
                  <span>{t('knowledge.chunks.index', { index: chunk.chunk_index })}</span>
                  {chunk.page_no !== null && (
                    <span>{t('knowledge.chunks.pageNo', { page: chunk.page_no })}</span>
                  )}
                  <span>{t('knowledge.chunks.chars', { count: chunk.char_count })}</span>
                  {chunk.token_count !== null && (
                    <span>{t('knowledge.chunks.tokens', { count: chunk.token_count })}</span>
                  )}
                </div>
                <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-ink">
                  {chunk.text}
                </p>
              </article>
            ))}
          </div>
          <div className="flex items-center justify-between">
            <Button
              variant="secondary"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              <ChevronLeft className="h-4 w-4" />
              {t('knowledge.chunks.previous')}
            </Button>
            <span className="text-xs text-ink-muted">
              {t('knowledge.chunks.pageOf', {
                page: Math.floor(offset / PAGE_SIZE) + 1,
                pages: Math.max(1, Math.ceil(total / PAGE_SIZE)),
              })}
            </span>
            <Button
              variant="secondary"
              size="sm"
              disabled={end >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              {t('knowledge.chunks.next')}
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
import { Play, RotateCw } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { KnowledgeBaseSettings, RetrievalSearchResult } from '../../lib/types'

interface KnowledgeRetrievalTabProps {
  kbId: string
  settings?: KnowledgeBaseSettings
}

export function KnowledgeRetrievalTab({ kbId, settings }: KnowledgeRetrievalTabProps) {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(settings?.retrieval.top_k ?? 5)
  const [hybrid, setHybrid] = useState(settings?.retrieval.hybrid_enabled ?? true)
  const [rerank, setRerank] = useState(settings?.retrieval.rerank_enabled ?? true)
  const [result, setResult] = useState<RetrievalSearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (settings === undefined) return
    setTopK(settings.retrieval.top_k)
    setHybrid(settings.retrieval.hybrid_enabled)
    setRerank(settings.retrieval.rerank_enabled)
  }, [settings])

  const search = async () => {
    const trimmed = query.trim()
    if (trimmed === '' || loading) return
    setLoading(true)
    setError(null)
    try {
      const response = await apiRequest<RetrievalSearchResult>(
        `/knowledge-bases/${kbId}/retrieval/search`,
        {
          method: 'POST',
          body: {
            query: trimmed,
            top_k: topK,
            hybrid_enabled: hybrid,
            rerank_enabled: rerank,
          },
        },
      )
      setResult(response)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <section className="rounded-card border border-border bg-surface p-4">
        <label className="block text-xs text-ink-muted">
          <span className="mb-1 block">{t('knowledge.retrieval.query')}</span>
          <Textarea
            rows={3}
            maxLength={500}
            value={query}
            placeholder={t('knowledge.retrieval.queryPlaceholder')}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) void search()
            }}
          />
        </label>
        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-ink-muted">
            {t('knowledge.retrieval.topK')}
            <Input
              type="number"
              min={1}
              max={20}
              value={topK}
              className="w-20"
              onChange={(event) => setTopK(Number(event.target.value) || 1)}
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={hybrid}
              onChange={(event) => setHybrid(event.target.checked)}
            />
            {t('knowledge.retrieval.hybrid')}
          </label>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={rerank}
              onChange={(event) => setRerank(event.target.checked)}
            />
            {t('knowledge.retrieval.rerank')}
          </label>
          <Button className="ml-auto" disabled={loading || query.trim() === ''} onClick={() => void search()}>
            {loading ? <Spinner /> : <Play className="h-4 w-4" />}
            {t('knowledge.retrieval.run')}
          </Button>
        </div>
      </section>

      {error !== null && (
        <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {result !== null && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
            <Badge tone="accent">{result.mode}</Badge>
            <span>{t('knowledge.retrieval.hits', { count: result.results.length })}</span>
            <span>{t('knowledge.retrieval.vectorMs', { ms: result.timings.vector_ms })}</span>
            <span>{t('knowledge.retrieval.lexicalMs', { ms: result.timings.lexical_ms })}</span>
            <span>{t('knowledge.retrieval.rerankMs', { ms: result.timings.rerank_ms })}</span>
            <span>{t('knowledge.retrieval.totalMs', { ms: result.timings.total_ms })}</span>
          </div>

          {result.results.length === 0 && (
            <p className="text-sm text-ink-muted">{t('knowledge.retrieval.noResults')}</p>
          )}

          <div className="space-y-3">
            {result.results.map((hit, index) => (
              <article key={hit.chunk_id} className="rounded-card border border-border bg-surface p-4">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
                  <Badge tone="neutral">#{index + 1}</Badge>
                  <span className="font-medium text-ink">{hit.filename}</span>
                  <span>{t('knowledge.chunks.index', { index: hit.chunk_index })}</span>
                  {hit.page_no !== null && (
                    <span>{t('knowledge.chunks.pageNo', { page: hit.page_no })}</span>
                  )}
                  <span className="ml-auto flex flex-wrap gap-2">
                    <span>
                      {t('knowledge.retrieval.vectorRank', { rank: hit.vector_rank ?? '—' })}
                    </span>
                    <span>
                      {t('knowledge.retrieval.lexicalRank', { rank: hit.lexical_rank ?? '—' })}
                    </span>
                    {hit.fused_score !== null && (
                      <span>
                        {t('knowledge.retrieval.fusedScore', {
                          score: hit.fused_score.toFixed(4),
                        })}
                      </span>
                    )}
                    {hit.rerank_score !== null && (
                      <span>
                        {t('knowledge.retrieval.rerankScore', {
                          score: hit.rerank_score.toFixed(4),
                        })}
                      </span>
                    )}
                  </span>
                </div>
                <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-ink">
                  {hit.text}
                </p>
              </article>
            ))}
          </div>
        </>
      )}

      {result === null && !loading && error === null && (
        <p className="text-sm text-ink-muted">{t('knowledge.retrieval.hint')}</p>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-sm text-ink-muted">
          <RotateCw className="h-4 w-4 animate-spin" />
          {t('knowledge.retrieval.running')}
        </div>
      )}
    </div>
  )
}
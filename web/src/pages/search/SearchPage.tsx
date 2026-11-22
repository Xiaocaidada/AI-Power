import { useQuery } from '@tanstack/react-query'
import { Search as SearchIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { SearchResponse } from '../../lib/types'

const TYPE_ORDER = [
  'conversation',
  'project',
  'agent',
  'prompt',
  'knowledge_base',
  'file',
]

export function SearchPage() {
  const { t } = useI18n()
  const [params, setParams] = useSearchParams()
  const initial = params.get('q') ?? ''
  const [value, setValue] = useState(initial)
  const query = initial.trim()

  useEffect(() => {
    setValue(initial)
  }, [initial])

  const results = useQuery({
    queryKey: ['global-search', query],
    queryFn: () =>
      apiRequest<SearchResponse>(`/search?q=${encodeURIComponent(query)}`),
    enabled: query !== '',
  })

  const submit = () => {
    setParams(value.trim() === '' ? {} : { q: value.trim() })
  }

  const grouped = new Map<string, SearchResponse['results']>()
  for (const result of results.data?.results ?? []) {
    grouped.set(result.type, [...(grouped.get(result.type) ?? []), result])
  }
  const orderedTypes = TYPE_ORDER.filter((type) => grouped.has(type))

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('search.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('search.lead')}</p>
      </header>

      <div className="mx-auto w-full max-w-4xl space-y-6 px-6 py-6">
        <div className="flex gap-2">
          <input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submit()
            }}
            placeholder={t('search.placeholder')}
            className="h-10 flex-1 rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
          />
          <Button onClick={submit}>
            <SearchIcon className="h-4 w-4" />
            {t('search.submit')}
          </Button>
        </div>

        {results.isLoading && <Spinner />}
        {query === '' && (
          <p className="py-10 text-center text-sm text-ink-muted">{t('search.hint')}</p>
        )}
        {query !== '' && results.data !== undefined && results.data.results.length === 0 && (
          <p className="py-10 text-center text-sm text-ink-muted">{t('search.empty')}</p>
        )}

        {orderedTypes.map((type) => (
          <section key={type}>
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-muted">
              {t(`search.type.${type}`)}
            </h2>
            <div className="divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface">
              {(grouped.get(type) ?? []).map((result) => (
                <Link
                  key={`${result.type}:${result.id}`}
                  to={result.href}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-surface-muted"
                >
                  <Badge tone="neutral">{t(`search.type.${type}`)}</Badge>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-ink">{result.title}</p>
                    <p className="truncate text-xs text-ink-muted">{result.subtitle}</p>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
import { useQuery } from '@tanstack/react-query'
import { Download, FileText } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Spinner } from '../../components/ui/spinner'
import { formatDate } from '../../lib/format'
import { apiDownload, apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { FileItem } from '../../lib/types'

const STATUSES = ['ready', 'uploaded', 'parsing', 'embedding', 'failed']

export function FilesPage() {
  const { t, language } = useI18n()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const files = useQuery({
    queryKey: ['files', search, status],
    queryFn: () =>
      apiRequest<FileItem[]>(
        `/files?${new URLSearchParams({
          ...(search.trim() !== '' ? { q: search.trim() } : {}),
          ...(status !== '' ? { status } : {}),
        }).toString()}`,
      ),
  })

  const download = async (file: FileItem) => {
    setBusy(file.id)
    try {
      const result = await apiDownload(`/documents/${file.id}/download`)
      const url = URL.createObjectURL(result.blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = result.filename ?? file.filename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('files.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('files.lead')}</p>
      </header>

      <div className="space-y-4 px-6 py-6">
        <div className="flex flex-wrap gap-2">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t('files.search')}
            className="h-9 w-full max-w-xs rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-accent focus:outline-none"
          />
          <select
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
          >
            <option value="">{t('files.allStatuses')}</option>
            {STATUSES.map((item) => (
              <option key={item} value={item}>
                {t(`files.status.${item}`)}
              </option>
            ))}
          </select>
        </div>

        {files.isLoading && <Spinner />}
        <div className="space-y-2">
          {(files.data ?? []).map((file) => (
            <article
              key={file.id}
              className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3"
            >
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-soft text-accent">
                <FileText className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">{file.filename}</p>
                <p className="truncate text-xs text-ink-muted">
                  <Link to={`/knowledge/${file.kb_id}`} className="hover:text-accent">
                    {file.kb_name}
                  </Link>{' '}
                  · {(file.size_bytes / 1024).toFixed(1)} KB ·{' '}
                  {formatDate(file.created_at, language)}
                </p>
              </div>
              <Badge
                tone={
                  file.status === 'ready'
                    ? 'success'
                    : file.status === 'failed'
                      ? 'danger'
                      : 'neutral'
                }
              >
                {t(`files.status.${file.status}`)}
              </Badge>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy === file.id}
                onClick={() => void download(file)}
              >
                <Download className="h-3.5 w-3.5" />
                {t('files.download')}
              </Button>
            </article>
          ))}
        </div>
        {files.data !== undefined && files.data.length === 0 && (
          <p className="rounded-2xl border border-dashed border-border px-6 py-16 text-center text-sm text-ink-muted">
            {t('files.empty')}
          </p>
        )}
      </div>
    </div>
  )
}
import { useQuery } from '@tanstack/react-query'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Spinner } from '../../components/ui/spinner'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { TraceRecord } from '../../lib/types'

interface TraceDialogProps {
  requestId: string | null
  onClose: () => void
}

function milliseconds(value: number | null): string {
  return value === null ? '—' : `${Math.round(value)} ms`
}

export function TraceDialog({ requestId, onClose }: TraceDialogProps) {
  const { t } = useI18n()
  const trace = useQuery({
    queryKey: ['trace', requestId],
    queryFn: () => apiRequest<TraceRecord>(`/traces/${requestId}`),
    enabled: requestId !== null,
    retry: false,
  })

  return (
    <Dialog
      open={requestId !== null}
      onClose={onClose}
      title={t('trace.title')}
      footer={
        <Button size="sm" variant="secondary" onClick={onClose}>
          {t('trace.close')}
        </Button>
      }
    >
      {trace.isLoading && (
        <span className="flex items-center gap-2 text-sm text-ink-muted">
          <Spinner />
          {t('trace.loading')}
        </span>
      )}
      {trace.isError && <p className="text-sm text-ink-muted">{t('trace.unavailable')}</p>}
      {trace.data !== undefined && (
        <div className="space-y-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-ink-muted">{t('trace.status')}</span>
            <Badge tone={trace.data.status === 'completed' ? 'success' : 'danger'}>
              {trace.data.status}
            </Badge>
          </div>
          <dl className="grid grid-cols-2 gap-3">
            <div>
              <dt className="text-xs text-ink-muted">{t('trace.provider')}</dt>
              <dd className="mt-0.5 font-mono text-xs text-ink">
                {trace.data.provider_id ?? '—'}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-ink-muted">{t('trace.model')}</dt>
              <dd className="mt-0.5 truncate font-mono text-xs text-ink">
                {trace.data.model ?? '—'}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-ink-muted">{t('trace.retrieval')}</dt>
              <dd className="mt-0.5 font-mono text-xs text-ink">
                {milliseconds(trace.data.retrieval_ms)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-ink-muted">{t('trace.ttft')}</dt>
              <dd className="mt-0.5 font-mono text-xs text-ink">
                {milliseconds(trace.data.ttft_ms)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-ink-muted">{t('trace.total')}</dt>
              <dd className="mt-0.5 font-mono text-xs text-ink">
                {milliseconds(trace.data.total_ms)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-ink-muted">{t('trace.attempts')}</dt>
              <dd className="mt-0.5 font-mono text-xs text-ink">{trace.data.attempts}</dd>
            </div>
          </dl>
          {trace.data.error_code !== null && (
            <div>
              <dt className="text-xs text-ink-muted">{t('trace.error')}</dt>
              <dd className="mt-0.5 font-mono text-xs text-danger">{trace.data.error_code}</dd>
            </div>
          )}
        </div>
      )}
    </Dialog>
  )
}
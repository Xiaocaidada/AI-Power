import { EmptyState } from '../components/ui/empty-state'
import { useI18n } from '../lib/i18n'

export function PlaceholderPage({ titleKey, leadKey }: { titleKey: string; leadKey: string }) {
  const { t } = useI18n()
  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t(titleKey)}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t(leadKey)}</p>
      </header>
      <EmptyState title={t('common.comingSoon')} />
    </div>
  )
}
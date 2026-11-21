import { useI18n } from '../../lib/i18n'
import { formatDate } from '../../lib/format'
import { useLogout } from '../../lib/useLogout'
import { useAuthStore } from '../../store/auth'
import { Button } from '../../components/ui/button'
import { cn } from '../../lib/utils'

export function ProfilePage() {
  const { t, language, setLanguage } = useI18n()
  const user = useAuthStore((state) => state.user)
  const logout = useLogout()

  const fields = [
    { label: t('profile.email'), value: user?.email ?? '—' },
    { label: t('profile.role'), value: user?.role ?? '—' },
    {
      label: t('profile.createdAt'),
      value: user !== null ? formatDate(user.created_at, language) : '—',
    },
  ]

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('profile.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('profile.lead')}</p>
      </header>

      <div className="max-w-2xl space-y-5 px-6 py-6">
        <section className="rounded-card border border-border bg-surface p-4">
          <dl className="grid gap-4 sm:grid-cols-3">
            {fields.map((field) => (
              <div key={field.label}>
                <dt className="text-xs text-ink-muted">{field.label}</dt>
                <dd className="mt-1 break-all text-sm text-ink">{field.value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="rounded-card border border-border bg-surface p-4">
          <p className="text-xs text-ink-muted">{t('profile.language')}</p>
          <div className="mt-2 inline-flex rounded-lg bg-surface-muted p-1 text-sm">
            <button
              type="button"
              onClick={() => setLanguage('zh')}
              className={cn(
                'rounded-md px-4 py-1.5',
                language === 'zh' ? 'bg-surface font-medium text-ink shadow-subtle' : 'text-ink-muted',
              )}
            >
              {t('common.chinese')}
            </button>
            <button
              type="button"
              onClick={() => setLanguage('en')}
              className={cn(
                'rounded-md px-4 py-1.5',
                language === 'en' ? 'bg-surface font-medium text-ink shadow-subtle' : 'text-ink-muted',
              )}
            >
              {t('common.english')}
            </button>
          </div>
        </section>

        <section className="rounded-card border border-border bg-surface p-4">
          <Button variant="danger" onClick={() => void logout()}>
            {t('profile.logout')}
          </Button>
        </section>
      </div>
    </div>
  )
}
import { BookOpen, Bot, Boxes, MessageSquare, Plug, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useI18n } from '../../lib/i18n'

const sections = [
  { key: 'providers', icon: Boxes, href: '/settings/providers' },
  { key: 'market', icon: Sparkles, href: '/models' },
  { key: 'chat', icon: MessageSquare, href: '/chat' },
  { key: 'knowledge', icon: BookOpen, href: '/knowledge' },
  { key: 'agents', icon: Bot, href: '/agents' },
  { key: 'plugins', icon: Plug, href: '/plugins' },
] as const

const faqs = ['cost', 'keys', 'models', 'start'] as const

export function HelpPage() {
  const { t } = useI18n()

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-12">
      <header className="max-w-2xl">
        <h1 className="font-serif text-3xl text-ink">{t('help.title')}</h1>
        <p className="mt-2 text-sm text-ink-muted">{t('help.lead')}</p>
      </header>

      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {sections.map(({ key, icon: Icon, href }) => (
          <Link
            key={key}
            to={href}
            className="rounded-2xl border border-border bg-surface p-5 transition-colors hover:border-accent/40"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-soft text-accent">
              <Icon className="h-4 w-4" />
            </span>
            <p className="mt-3 text-sm font-medium text-ink">
              {t(`help.sections.${key}.title`)}
            </p>
            <p className="mt-1 text-xs leading-5 text-ink-muted">
              {t(`help.sections.${key}.body`)}
            </p>
          </Link>
        ))}
      </div>

      <section className="mt-10">
        <h2 className="font-serif text-2xl text-ink">{t('help.faq.title')}</h2>
        <div className="mt-4 divide-y divide-border overflow-hidden rounded-2xl border border-border bg-surface">
          {faqs.map((key) => (
            <details key={key} className="group px-5 py-4">
              <summary className="cursor-pointer list-none text-sm font-medium text-ink">
                {t(`help.faq.${key}.q`)}
              </summary>
              <p className="mt-2 text-sm leading-6 text-ink-muted">
                {t(`help.faq.${key}.a`)}
              </p>
            </details>
          ))}
        </div>
      </section>
    </div>
  )
}
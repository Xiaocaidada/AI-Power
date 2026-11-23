import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { MemorySettings } from '../../lib/types'

const CATEGORIES = [
  'preference',
  'profile',
  'project',
  'technical',
  'experience',
  'decision',
  'relation',
  'fact',
] as const

export function MemorySettingsPanel() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [form, setForm] = useState<MemorySettings | null>(null)
  const [blockedText, setBlockedText] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const settings = useQuery({
    queryKey: ['memory-settings'],
    queryFn: () => apiRequest<MemorySettings>('/memories/settings'),
  })

  useEffect(() => {
    if (settings.data === undefined) return
    setForm(settings.data)
    setBlockedText((settings.data.blocked_topics ?? []).join(', '))
  }, [settings.data])

  if (settings.isLoading || form === null) {
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    )
  }

  const update = <K extends keyof MemorySettings>(key: K, value: MemorySettings[K]) =>
    setForm((current) => (current === null ? current : { ...current, [key]: value }))

  const toggleCategory = (category: string) => {
    const current = form.allowed_categories ?? []
    update(
      'allowed_categories',
      current.includes(category)
        ? current.filter((item) => item !== category)
        : [...current, category],
    )
  }

  const save = async () => {
    setSaving(true)
    setMessage(null)
    setError(null)
    try {
      const saved = await apiRequest<MemorySettings>('/memories/settings', {
        method: 'PATCH',
        body: {
          ...form,
          blocked_topics: blockedText
            .split(',')
            .map((item) => item.trim())
            .filter((item) => item !== ''),
        },
      })
      setForm(saved)
      setBlockedText((saved.blocked_topics ?? []).join(', '))
      setMessage(t('memory.settings.saved'))
      await queryClient.invalidateQueries({ queryKey: ['memory-settings'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-3xl space-y-4">
      <section className="rounded-card border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-ink">
            {t('memory.settings.title')}
          </h2>
          <Badge tone={form.enabled ? 'success' : 'neutral'}>
            {form.enabled ? t('memory.settings.on') : t('memory.settings.off')}
          </Badge>
        </div>
        <p className="mt-1 text-xs text-ink-muted">{t('memory.settings.lead')}</p>
        <div className="mt-3 space-y-2">
          <Toggle
            label={t('memory.settings.enabled')}
            hint={t('memory.settings.enabledHint')}
            checked={form.enabled}
            onChange={(value) => update('enabled', value)}
          />
          <Toggle
            label={t('memory.settings.autoExtract')}
            hint={t('memory.settings.autoExtractHint')}
            checked={form.auto_extract}
            onChange={(value) => update('auto_extract', value)}
          />
          <Toggle
            label={t('memory.settings.requireConfirmation')}
            hint={t('memory.settings.requireConfirmationHint')}
            checked={form.require_confirmation}
            onChange={(value) => update('require_confirmation', value)}
          />
          <Toggle
            label={t('memory.settings.autoSave')}
            hint={t('memory.settings.autoSaveHint')}
            checked={form.auto_save}
            onChange={(value) => update('auto_save', value)}
          />
          <Toggle
            label={t('memory.settings.allowProject')}
            hint={t('memory.settings.allowProjectHint')}
            checked={form.allow_project_extract}
            onChange={(value) => update('allow_project_extract', value)}
          />
          <Toggle
            label={t('memory.settings.allowAgent')}
            hint={t('memory.settings.allowAgentHint')}
            checked={form.allow_agent_extract}
            onChange={(value) => update('allow_agent_extract', value)}
          />
          <Toggle
            label={t('memory.settings.allowCrossModel')}
            hint={t('memory.settings.allowCrossModelHint')}
            checked={form.allow_cross_model}
            onChange={(value) => update('allow_cross_model', value)}
          />
        </div>
      </section>

      <section className="rounded-card border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-ink">
          {t('memory.settings.categories')}
        </h2>
        <p className="mt-1 text-xs text-ink-muted">
          {t('memory.settings.categoriesHint')}
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {CATEGORIES.map((category) => (
            <label
              key={category}
              className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-1 text-xs text-ink"
            >
              <input
                type="checkbox"
                checked={(form.allowed_categories ?? []).includes(category)}
                onChange={() => toggleCategory(category)}
              />
              {t(`memory.category.${category}`)}
            </label>
          ))}
        </div>
      </section>

      <section className="rounded-card border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold text-ink">
          {t('memory.settings.injection')}
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-ink-muted">
            <span className="mb-1 block">{t('memory.settings.maxItems')}</span>
            <Input
              type="number"
              min={1}
              max={50}
              value={form.max_inject_items}
              onChange={(event) =>
                update('max_inject_items', Number(event.target.value) || 1)
              }
            />
          </label>
          <label className="text-xs text-ink-muted">
            <span className="mb-1 block">{t('memory.settings.maxChars')}</span>
            <Input
              type="number"
              min={200}
              max={20000}
              value={form.max_inject_chars}
              onChange={(event) =>
                update('max_inject_chars', Number(event.target.value) || 200)
              }
            />
          </label>
          <label className="text-xs text-ink-muted">
            <span className="mb-1 block">{t('memory.settings.retention')}</span>
            <Input
              type="number"
              min={1}
              max={3650}
              value={form.retention_days ?? ''}
              onChange={(event) =>
                update(
                  'retention_days',
                  event.target.value === '' ? null : Number(event.target.value),
                )
              }
            />
          </label>
          <label className="text-xs text-ink-muted sm:col-span-2">
            <span className="mb-1 block">{t('memory.settings.blockedTopics')}</span>
            <Input
              value={blockedText}
              onChange={(event) => setBlockedText(event.target.value)}
              placeholder={t('memory.settings.blockedPlaceholder')}
            />
          </label>
        </div>
      </section>

      <div className="flex items-center gap-3">
        <Button size="sm" disabled={saving} onClick={() => void save()}>
          <Save className="h-3.5 w-3.5" />
          {t('common.save')}
        </Button>
        {message !== null && <span className="text-xs text-success">{message}</span>}
        {error !== null && <span className="text-xs text-danger">{error}</span>}
      </div>
    </div>
  )
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string
  hint: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <label className="flex items-start gap-2 text-sm text-ink">
      <input
        type="checkbox"
        className="mt-1"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>
        <span className="font-medium">{label}</span>
        <span className="block text-xs text-ink-muted">{hint}</span>
      </span>
    </label>
  )
}
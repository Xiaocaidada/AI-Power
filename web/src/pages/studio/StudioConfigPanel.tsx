import { Save } from 'lucide-react'

import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { MultiPopoverSelect } from '../../components/ui/multi-popover-select'
import { PopoverSelect } from '../../components/ui/popover-select'
import { useI18n } from '../../lib/i18n'
import type { KnowledgeBase, Plugin } from '../../lib/types'
import type { ModelChoice, StudioAgentDraft } from './types'

interface StudioConfigPanelProps {
  draft: StudioAgentDraft
  models: ModelChoice[]
  knowledgeBases: KnowledgeBase[]
  plugins: Plugin[]
  hasWorkflow: boolean
  saving: boolean
  error: string | null
  onChange: (patch: Partial<StudioAgentDraft>) => void
  onSave: () => void
}

const TOOLS = ['kb_search', 'current_time', 'calculator']

export function StudioConfigPanel({
  draft,
  models,
  knowledgeBases,
  plugins,
  hasWorkflow,
  saving,
  error,
  onChange,
  onSave,
}: StudioConfigPanelProps) {
  const { t } = useI18n()
  const modeNeedsWorkflow =
    draft.mode !== 'autonomous' && !hasWorkflow

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto grid w-full max-w-6xl gap-4 px-6 py-6 lg:grid-cols-2">
        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="text-sm font-medium text-ink">{t('studio.basic')}</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-[5rem_1fr]">
            <label className="text-xs text-ink-muted">
              {t('studio.icon')}
              <Input
                className="mt-1 text-center text-xl"
                value={draft.icon}
                maxLength={8}
                onChange={(event) => onChange({ icon: event.target.value })}
              />
            </label>
            <label className="text-xs text-ink-muted">
              {t('studio.name')}
              <Input
                className="mt-1"
                value={draft.name}
                onChange={(event) => onChange({ name: event.target.value })}
              />
            </label>
          </div>
          <label className="mt-3 block text-xs text-ink-muted">
            {t('studio.description')}
            <Input
              className="mt-1"
              value={draft.description}
              onChange={(event) => onChange({ description: event.target.value })}
            />
          </label>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-ink-muted">
              {t('studio.category')}
              <Input
                className="mt-1"
                value={draft.category}
                onChange={(event) => onChange({ category: event.target.value })}
              />
            </label>
            <label className="text-xs text-ink-muted">
              {t('studio.visibility')}
              <PopoverSelect
                label={t('studio.visibility')}
                value={draft.visibility}
                options={[
                  { value: 'private', label: t('studio.private') },
                  { value: 'shared', label: t('studio.shared') },
                ]}
                onChange={(value) =>
                  onChange({ visibility: value as 'private' | 'shared' })
                }
              />
            </label>
          </div>
          <label className="mt-3 block text-xs text-ink-muted">
            {t('studio.welcome')}
            <Input
              className="mt-1"
              value={draft.welcomeMessage}
              onChange={(event) => onChange({ welcomeMessage: event.target.value })}
            />
          </label>
          <label className="mt-3 block text-xs text-ink-muted">
            {t('studio.examples')}
            <textarea
              value={draft.examples}
              onChange={(event) => onChange({ examples: event.target.value })}
              placeholder={t('studio.examplesHint')}
              className="mt-1 min-h-20 w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs text-ink"
            />
          </label>
          <label className="mt-3 block text-xs text-ink-muted">
            {t('studio.usageInstructions')}
            <textarea
              value={draft.usageInstructions}
              onChange={(event) => onChange({ usageInstructions: event.target.value })}
              className="mt-1 min-h-20 w-full rounded-lg border border-border bg-surface px-3 py-2 text-xs text-ink"
            />
          </label>
        </section>

        <section className="rounded-card border border-border bg-surface p-4">
          <h2 className="text-sm font-medium text-ink">{t('studio.behavior')}</h2>
          <label className="mt-3 block text-xs text-ink-muted">
            {t('studio.instructions')}
            <textarea
              value={draft.instructions}
              onChange={(event) => onChange({ instructions: event.target.value })}
              className="mt-1 min-h-40 w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs text-ink"
            />
          </label>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-ink-muted">
              {t('studio.mode')}
              <PopoverSelect
                label={t('studio.mode')}
                value={draft.mode}
                options={[
                  { value: 'autonomous', label: t('studio.modeAutonomous') },
                  { value: 'workflow', label: t('studio.modeWorkflow') },
                  { value: 'hybrid', label: t('studio.modeHybrid') },
                ]}
                onChange={(value) =>
                  onChange({ mode: value as StudioAgentDraft['mode'] })
                }
              />
            </label>
            <label className="text-xs text-ink-muted">
              {t('studio.model')}
              <PopoverSelect
                label={t('studio.model')}
                value={draft.providerChoice}
                options={[
                  { value: 'auto', label: t('models.auto') },
                  ...models.map((choice) => ({
                    value: `m:${choice.provider_id}:${choice.model}`,
                    label: choice.label,
                  })),
                ]}
                onChange={(value) => onChange({ providerChoice: value })}
              />
            </label>
          </div>
          {modeNeedsWorkflow && (
            <p className="mt-2 text-[11px] text-warning">{t('studio.modeNeedsWorkflow')}</p>
          )}
          <div className="mt-3">
            <MultiPopoverSelect
              label={t('studio.knowledgeBases')}
              values={draft.kbIds}
              options={knowledgeBases.map((kb) => ({
                value: kb.id,
                label: kb.name,
              }))}
              onChange={(values) => onChange({ kbIds: values })}
              placeholder={t('studio.noKnowledgeBases')}
            />
          </div>
          <div className="mt-3">
            <p className="text-xs text-ink-muted">{t('studio.tools')}</p>
            <div className="mt-1 flex flex-wrap gap-3">
              {TOOLS.map((tool) => (
                <label key={tool} className="flex items-center gap-1.5 text-xs text-ink">
                  <input
                    type="checkbox"
                    checked={draft.tools.includes(tool)}
                    onChange={(event) =>
                      onChange({
                        tools: event.target.checked
                          ? [...draft.tools, tool]
                          : draft.tools.filter((item) => item !== tool),
                      })
                    }
                  />
                  {tool}
                </label>
              ))}
            </div>
          </div>
          <label className="mt-3 flex items-center gap-2 text-xs text-ink">
            <input
              type="checkbox"
              checked={draft.memoryEnabled}
              onChange={(event) => onChange({ memoryEnabled: event.target.checked })}
            />
            {t('studio.memoryEnabled')}
          </label>
          <p className="mt-1 text-[10px] text-ink-muted">{t('studio.memoryHint')}</p>
          <div className="mt-3">
            <MultiPopoverSelect
              label={t('studio.plugins')}
              values={draft.pluginIds}
              options={plugins.map((plugin) => ({
                value: plugin.id,
                label: plugin.name,
              }))}
              onChange={(values) => onChange({ pluginIds: values })}
              placeholder={t('studio.noPlugins')}
            />
          </div>
          <div className="mt-4 flex items-center gap-3">
            <Button size="sm" disabled={saving} onClick={onSave}>
              <Save className="h-3.5 w-3.5" />
              {t('common.save')}
            </Button>
            {error !== null && <p className="text-xs text-danger">{error}</p>}
          </div>
        </section>
      </div>
    </div>
  )
}
import { Save } from 'lucide-react'

import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { MultiPopoverSelect } from '../../components/ui/multi-popover-select'
import { PopoverSelect } from '../../components/ui/popover-select'
import { useI18n } from '../../lib/i18n'
import type { KnowledgeBase, Plugin } from '../../lib/types'
import { StudioToolsSection } from './StudioToolsSection'
import type { ModelChoice, StudioAgentDraft } from './types'

interface StudioConfigPanelProps {
  agentId: string
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

export function StudioConfigPanel({
  agentId,
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
          <label className="mt-3 block text-xs text-ink-muted">
            {t('studio.coverUrl')}
            <Input
              className="mt-1"
              value={draft.coverUrl}
              placeholder="https://…"
              onChange={(event) => onChange({ coverUrl: event.target.value })}
            />
            <span className="mt-1 block text-[10px] text-ink-muted">
              {t('studio.coverUrlHint')}
            </span>
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
          <div className="mt-3 rounded-lg border border-border bg-surface-muted/40 p-3">
            <p className="text-xs font-medium text-ink">{t('studio.generationSettings')}</p>
            <p className="mt-0.5 text-[10px] text-ink-muted">
              {t('studio.generationSettingsHint')}
            </p>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              <label className="text-xs text-ink-muted">
                {t('studio.temperature')}
                <Input
                  className="mt-1"
                  inputMode="decimal"
                  value={draft.temperature}
                  placeholder="0.7"
                  onChange={(event) => onChange({ temperature: event.target.value })}
                />
              </label>
              <label className="text-xs text-ink-muted">
                {t('studio.maxTokens')}
                <Input
                  className="mt-1"
                  inputMode="numeric"
                  value={draft.maxTokens}
                  placeholder="2048"
                  onChange={(event) => onChange({ maxTokens: event.target.value })}
                />
              </label>
              <label className="text-xs text-ink-muted">
                {t('studio.topP')}
                <Input
                  className="mt-1"
                  inputMode="decimal"
                  value={draft.topP}
                  placeholder="1"
                  onChange={(event) => onChange({ topP: event.target.value })}
                />
              </label>
            </div>
          </div>
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
          <StudioToolsSection
            agentId={agentId}
            tools={draft.tools}
            onChange={(tools) => onChange({ tools })}
          />
          <label className="mt-3 flex items-center gap-2 text-xs text-ink">
            <input
              type="checkbox"
              checked={draft.memoryEnabled}
              onChange={(event) => onChange({ memoryEnabled: event.target.checked })}
            />
            {t('studio.memoryEnabled')}
          </label>
          <p className="mt-1 text-[10px] text-ink-muted">{t('studio.memoryHint')}</p>
          {draft.memoryEnabled && (
            <div className="mt-2 rounded-lg border border-border bg-surface-muted/40 p-3">
              <p className="text-[11px] font-medium text-ink">
                {t('studio.memoryPermissions')}
              </p>
              <p className="mt-0.5 text-[10px] text-ink-muted">
                {t('studio.memoryPermissionsHint')}
              </p>
              <div className="mt-2 flex flex-wrap gap-3 text-xs text-ink">
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={draft.memoryReadGlobal}
                    onChange={(event) =>
                      onChange({ memoryReadGlobal: event.target.checked })
                    }
                  />
                  {t('memory.scopeType.global')}
                </label>
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={draft.memoryReadProject}
                    onChange={(event) =>
                      onChange({ memoryReadProject: event.target.checked })
                    }
                  />
                  {t('memory.scopeType.project')}
                </label>
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={draft.memoryReadAgent}
                    onChange={(event) =>
                      onChange({ memoryReadAgent: event.target.checked })
                    }
                  />
                  {t('memory.scopeType.agent')}
                </label>
              </div>
              <label className="mt-2 flex items-center gap-2 text-xs text-ink">
                <input
                  type="checkbox"
                  checked={draft.memoryWrite}
                  onChange={(event) =>
                    onChange({ memoryWrite: event.target.checked })
                  }
                />
                {t('studio.memoryWrite')}
              </label>
              {draft.memoryWrite && (
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  <div className="text-xs text-ink-muted">
                    {t('studio.memoryWriteScope')}
                    <PopoverSelect
                      label={t('studio.memoryWriteScope')}
                      value={draft.memoryWriteScope}
                      options={[
                        { value: 'agent', label: t('memory.scopeType.agent') },
                        { value: 'project', label: t('memory.scopeType.project') },
                        { value: 'global', label: t('memory.scopeType.global') },
                      ]}
                      onChange={(value) =>
                        onChange({
                          memoryWriteScope: value as StudioAgentDraft['memoryWriteScope'],
                        })
                      }
                    />
                  </div>
                  <div className="text-xs text-ink-muted">
                    {t('studio.memoryWriteMode')}
                    <PopoverSelect
                      label={t('studio.memoryWriteMode')}
                      value={draft.memoryWriteMode}
                      options={[
                        { value: 'candidate', label: t('studio.memoryModeCandidate') },
                        { value: 'create', label: t('studio.memoryModeCreate') },
                        { value: 'upsert', label: t('studio.memoryModeUpsert') },
                      ]}
                      onChange={(value) =>
                        onChange({
                          memoryWriteMode: value as StudioAgentDraft['memoryWriteMode'],
                        })
                      }
                    />
                  </div>
                </div>
              )}
            </div>
          )}
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
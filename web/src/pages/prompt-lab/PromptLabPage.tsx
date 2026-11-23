import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, GitCompare, Play, Save, Square } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { PopoverSelect } from '../../components/ui/popover-select'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import { streamPromptOutput } from '../../lib/sse'
import type {
  ModelEntry,
  PersonalModel,
  PromptDiff,
  PromptDiffLine,
  PromptExperiment,
  PromptExperimentOutput,
  PromptTemplate,
} from '../../lib/types'

function DiffBlock({ title, lines }: { title: string; lines: PromptDiffLine[] }) {
  if (lines.length === 0) return null
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-ink">{title}</p>
      <div className="max-h-72 overflow-auto rounded-lg border border-border font-mono text-[11px]">
        {lines.map((line, index) => (
          <div
            key={`${line.type}-${line.old_line}-${line.new_line}-${index}`}
            className={
              line.type === 'insert'
                ? 'flex bg-success/10'
                : line.type === 'delete'
                  ? 'flex bg-danger/10'
                  : 'flex'
            }
          >
            <span className="w-8 shrink-0 select-none border-r border-border px-1 text-right text-ink-muted">
              {line.old_line ?? ''}
            </span>
            <span className="w-8 shrink-0 select-none border-r border-border px-1 text-right text-ink-muted">
              {line.new_line ?? ''}
            </span>
            <span className="w-4 shrink-0 select-none text-center text-ink-muted">
              {line.type === 'insert' ? '+' : line.type === 'delete' ? '-' : ' '}
            </span>
            <span className="whitespace-pre-wrap break-all px-1 text-ink">
              {line.text || ' '}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

interface ModelChoice {
  provider_id: string
  model: string
  label: string
}

function OutputColumn({
  experiment,
  output,
  onChanged,
}: {
  experiment: PromptExperiment
  output: PromptExperimentOutput
  onChanged: () => void
}) {
  const { t } = useI18n()
  const [item, setItem] = useState(output)
  const [streaming, setStreaming] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)
  const startedRef = useRef(false)

  useEffect(() => {
    setItem(output)
  }, [output])

  const start = async () => {
    if (controllerRef.current !== null) return
    setStreaming(true)
    setItem((prev) => ({ ...prev, status: 'streaming', content: '' }))
    const controller = new AbortController()
    controllerRef.current = controller
    try {
      await streamPromptOutput({
        experimentId: experiment.id,
        outputId: item.id,
        signal: controller.signal,
        onEvent: (event) => {
          const data = event.data as Record<string, unknown> | null
          if (data === null) return
          if (event.event === 'delta') {
            setItem((prev) => ({ ...prev, content: prev.content + String(data.text ?? '') }))
          } else if (event.event === 'usage') {
            setItem((prev) => ({
              ...prev,
              prompt_tokens:
                typeof data.prompt_tokens === 'number' ? data.prompt_tokens : null,
              completion_tokens:
                typeof data.completion_tokens === 'number' ? data.completion_tokens : null,
              cost: typeof data.cost === 'number' ? data.cost : 0,
            }))
          } else if (event.event === 'done') {
            setItem((prev) => ({
              ...prev,
              status: 'completed',
              ttft_ms: typeof data.ttft_ms === 'number' ? data.ttft_ms : null,
              total_ms: typeof data.total_ms === 'number' ? data.total_ms : null,
            }))
          } else if (event.event === 'error') {
            setItem((prev) => ({
              ...prev,
              status: 'failed',
              error_code: String(data.code ?? 'internal_error'),
            }))
          }
        },
      })
    } catch {
      if (controller.signal.aborted) {
        setItem((prev) => ({ ...prev, status: 'cancelled' }))
      } else {
        setItem((prev) => ({ ...prev, status: 'failed' }))
      }
    } finally {
      controllerRef.current = null
      setStreaming(false)
      onChanged()
    }
  }

  useEffect(() => {
    if (item.status !== 'queued' || startedRef.current) return
    startedRef.current = true
    void start()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.status])

  useEffect(
    () => () => {
      controllerRef.current?.abort()
    },
    [],
  )

  return (
    <article className="flex min-h-0 flex-col rounded-card border border-border bg-surface">
      <header className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-ink">{item.model}</p>
          <p className="truncate text-[10px] text-ink-muted">{item.provider_id}</p>
        </div>
        <div className="flex items-center gap-1">
          <Badge
            tone={
              item.status === 'completed'
                ? 'success'
                : item.status === 'failed'
                  ? 'danger'
                  : 'neutral'
            }
          >
            {item.status}
          </Badge>
          {streaming && (
            <Button
              variant="ghost"
              size="sm"
              aria-label={t('arena.stop')}
              onClick={() => controllerRef.current?.abort()}
            >
              <Square className="h-3 w-3" />
            </Button>
          )}
        </div>
      </header>
      <div className="min-h-[14rem] flex-1 overflow-y-auto px-3 py-2">
        {item.content ? (
          <div className="markdown text-sm text-ink">
            <ReactMarkdown>{item.content}</ReactMarkdown>
          </div>
        ) : (
          <p className="text-xs text-ink-muted">
            {item.status === 'failed' ? item.error_code : t('promptLab.generating')}
          </p>
        )}
      </div>
      <footer className="grid grid-cols-2 gap-1 border-t border-border px-3 py-1.5 text-[10px] text-ink-muted">
        <span>TTFT {item.ttft_ms !== null ? `${item.ttft_ms} ms` : '—'}</span>
        <span>Total {item.total_ms !== null ? `${item.total_ms} ms` : '—'}</span>
        <span>
          {item.prompt_tokens ?? 0} + {item.completion_tokens ?? 0} tokens
        </span>
        <span>~${item.cost.toFixed(6)}</span>
      </footer>
    </article>
  )
}

export function PromptLabPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState('')
  const [versionIndex, setVersionIndex] = useState(0)
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [userPrompt, setUserPrompt] = useState('')
  const [variables, setVariables] = useState<Record<string, string>>({})
  const [models, setModels] = useState<ModelChoice[]>([])
  const [experiment, setExperiment] = useState<PromptExperiment | null>(null)
  const [preview, setPreview] = useState<{ system: string; user: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [diffOpen, setDiffOpen] = useState(false)
  const [diffFrom, setDiffFrom] = useState('')
  const [diffTo, setDiffTo] = useState('')
  const [diff, setDiff] = useState<PromptDiff | null>(null)
  const [diffError, setDiffError] = useState<string | null>(null)
  const [diffBusy, setDiffBusy] = useState(false)

  const templates = useQuery({
    queryKey: ['prompt-templates', 'lab'],
    queryFn: () => apiRequest<PromptTemplate[]>('/prompt-templates'),
  })
  const experiments = useQuery({
    queryKey: ['prompt-experiments'],
    queryFn: () => apiRequest<PromptExperiment[]>('/prompt-lab/experiments?limit=20'),
  })
  const platformModels = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
    staleTime: 60_000,
  })
  const personalModels = useQuery({
    queryKey: ['provider-configs', 'models'],
    queryFn: () => apiRequest<PersonalModel[]>('/provider-configs/models'),
    staleTime: 60_000,
  })

  const selected = (templates.data ?? []).find((item) => item.id === selectedId)
  const latest = selected?.versions[versionIndex] ?? selected?.versions[0]
  const readOnly = selected?.scope === 'platform'

  useEffect(() => {
    if (selectedId === '' && (templates.data ?? []).length > 0) {
      setSelectedId(templates.data?.[0]?.id ?? '')
    }
  }, [selectedId, templates.data])

  useEffect(() => {
    if (latest === undefined) return
    setSystemPrompt(latest.system_prompt)
    setUserPrompt(latest.user_prompt ?? '')
    const defaults: Record<string, string> = {}
    for (const variable of latest.variables) {
      defaults[variable] =
        latest.variable_definitions?.find((item) => item.name === variable)?.default ?? ''
    }
    setVariables(defaults)
    setPreview(null)
    setExperiment(null)
  }, [latest])

  const choices: ModelChoice[] = [
    ...(platformModels.data ?? [])
      .filter((item) => item.available)
      .map((item) => ({
        provider_id: item.provider_id,
        model: item.model_id,
        label: `${item.display_name} · ${item.provider_id}`,
      })),
    ...(personalModels.data ?? []).map((item) => ({
      provider_id: item.provider_id,
      model: item.model_id,
      label: `${item.display_name} · ${item.provider_name}`,
    })),
  ]
  const selectedModelKeys = new Set(models.map((item) => `${item.provider_id}/${item.model}`))

  const toggleModel = (choice: ModelChoice) => {
    const key = `${choice.provider_id}/${choice.model}`
    setModels((prev) =>
      prev.some((item) => `${item.provider_id}/${item.model}` === key)
        ? prev.filter((item) => `${item.provider_id}/${item.model}` !== key)
        : prev.length >= 4
          ? prev
          : [...prev, choice],
    )
  }

  const createTemplate = async () => {
    if (name.trim() === '' || systemPrompt.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      const created = await apiRequest<PromptTemplate>('/prompt-templates', {
        method: 'POST',
        body: {
          name: name.trim(),
          description: '',
          category: 'general',
          system_prompt: systemPrompt.trim(),
          user_prompt: userPrompt.trim(),
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['prompt-templates'] })
      setCreateOpen(false)
      setName('')
      setSelectedId(created.id)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const saveVersion = async () => {
    if (selected === undefined || readOnly) return
    setBusy(true)
    setError(null)
    try {
      await apiRequest(`/prompt-templates/${selected.id}/versions`, {
        method: 'POST',
        body: {
          system_prompt: systemPrompt,
          user_prompt: userPrompt,
          variable_definitions:
            latest?.variables.map((variable) => ({
              name: variable,
              description: '',
              required: true,
              default: variables[variable] ?? '',
            })) ?? [],
          parameters: latest?.parameters ?? {},
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['prompt-templates'] })
      setVersionIndex(0)
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const renderPreview = async () => {
    if (selected === undefined) return
    setBusy(true)
    setError(null)
    try {
      const result = await apiRequest<{
        system_prompt: string
        user_prompt: string
      }>(`/prompt-templates/${selected.id}/render`, {
        method: 'POST',
        body: { variables },
      })
      setPreview({ system: result.system_prompt, user: result.user_prompt })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const run = async () => {
    if (selected === undefined || models.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const created = await apiRequest<PromptExperiment>('/prompt-lab/experiments', {
        method: 'POST',
        body: {
          template_id: selected.id,
          version: null,
          variables,
          models: models.map(({ provider_id, model }) => ({ provider_id, model })),
          parameters: latest?.parameters ?? {},
        },
      })
      setExperiment(created)
      await queryClient.invalidateQueries({ queryKey: ['prompt-experiments'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(false)
    }
  }

  const rate = async (rating: 'good' | 'bad') => {
    if (experiment === null) return
    await apiRequest(`/prompt-lab/experiments/${experiment.id}`, {
      method: 'PATCH',
      body: { rating, note: experiment.note },
    })
    setExperiment({ ...experiment, rating })
  }

  const openHistory = (item: PromptExperiment) => {
    setExperiment(item)
    setPreview(null)
  }

  const openDiff = () => {
    if (selected === undefined || selected.versions.length < 2) return
    const latestVersion = selected.versions[0]?.version ?? 1
    const previousVersion = selected.versions[1]?.version ?? latestVersion
    setDiffFrom(String(previousVersion))
    setDiffTo(String(latestVersion))
    setDiff(null)
    setDiffError(null)
    setDiffOpen(true)
  }

  const loadDiff = async () => {
    if (selected === undefined) return
    setDiffBusy(true)
    setDiffError(null)
    try {
      const params = new URLSearchParams({ from_version: diffFrom })
      if (diffTo !== '') params.set('to_version', diffTo)
      const result = await apiRequest<PromptDiff>(
        `/prompt-templates/${selected.id}/diff?${params.toString()}`,
      )
      setDiff(result)
    } catch (caught) {
      setDiffError(t(errorTextKey(caught)))
    } finally {
      setDiffBusy(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <FlaskConical className="h-5 w-5 text-accent" />
          {t('promptLab.title')}
        </h1>
        <p className="mt-1 text-sm text-ink-muted">{t('promptLab.lead')}</p>
      </header>

      <div className="mx-auto grid w-full max-w-7xl gap-4 px-6 py-6 xl:grid-cols-[15rem_1.6fr_1fr]">
        <aside className="rounded-card border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <p className="text-sm font-medium">{t('promptLab.templates')}</p>
            <Button size="sm" variant="ghost" onClick={() => setCreateOpen(true)}>
              + {t('common.create')}
            </Button>
          </div>
          <div className="max-h-[60vh] divide-y divide-border overflow-y-auto">
            {(templates.data ?? []).map((template) => (
              <button
                key={template.id}
                type="button"
                onClick={() => {
                  setSelectedId(template.id)
                  setVersionIndex(0)
                }}
                className={`block w-full px-3 py-2 text-left ${
                  selectedId === template.id
                    ? 'bg-accent-soft text-accent'
                    : 'hover:bg-surface-muted'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="truncate text-xs font-medium">{template.name}</span>
                  {template.scope === 'platform' && <Badge tone="neutral">P</Badge>}
                </div>
                <p className="truncate text-[10px] text-ink-muted">{template.description}</p>
              </button>
            ))}
          </div>
        </aside>

        <section className="space-y-3">
          {selected === undefined ? (
            <p className="text-sm text-ink-muted">{t('promptLab.selectTemplate')}</p>
          ) : (
            <>
              <div className="rounded-card border border-border bg-surface p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-ink">{selected.name}</p>
                    <p className="text-[11px] text-ink-muted">
                      {selected.versions.length > 1 ? (
                        <select
                          value={versionIndex}
                          onChange={(event) => setVersionIndex(Number(event.target.value))}
                          className="mr-1 rounded border border-border bg-surface px-1 text-[11px]"
                        >
                          {selected.versions.map((version, index) => (
                            <option key={version.id} value={index}>
                              v{version.version}
                            </option>
                          ))}
                        </select>
                      ) : (
                        `v${latest?.version ?? 1}`
                      )}{' '}
                      · {selected.scope}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {selected.versions.length > 1 && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={openDiff}
                      >
                        <GitCompare className="h-3.5 w-3.5" />
                        {t('promptLab.diff')}
                      </Button>
                    )}
                    {!readOnly && (
                      <Button size="sm" disabled={busy} onClick={() => void saveVersion()}>
                        <Save className="h-3.5 w-3.5" />
                        {t('promptLab.saveVersion')}
                      </Button>
                    )}
                  </div>
                </div>
                <label className="mt-3 block text-xs text-ink-muted">
                  System Prompt
                  <textarea
                    value={systemPrompt}
                    readOnly={readOnly}
                    onChange={(event) => setSystemPrompt(event.target.value)}
                    className="mt-1 min-h-28 w-full resize-y rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs text-ink"
                  />
                </label>
                <label className="mt-2 block text-xs text-ink-muted">
                  User Prompt
                  <textarea
                    value={userPrompt}
                    readOnly={readOnly}
                    onChange={(event) => setUserPrompt(event.target.value)}
                    className="mt-1 min-h-20 w-full resize-y rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs text-ink"
                  />
                </label>
              </div>

              <div className="rounded-card border border-border bg-surface p-4">
                <p className="text-sm font-medium">{t('promptLab.variables')}</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {(latest?.variables ?? []).map((variable) => (
                    <label key={variable} className="text-xs text-ink-muted">
                      {`{{${variable}}}`}
                      <Input
                        className="mt-1"
                        value={variables[variable] ?? ''}
                        onChange={(event) =>
                          setVariables((prev) => ({
                            ...prev,
                            [variable]: event.target.value,
                          }))
                        }
                      />
                    </label>
                  ))}
                  {(latest?.variables ?? []).length === 0 && (
                    <p className="text-xs text-ink-muted">{t('promptLab.noVariables')}</p>
                  )}
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={busy}
                    onClick={() => void renderPreview()}
                  >
                    {t('promptLab.preview')}
                  </Button>
                  <Button
                    size="sm"
                    disabled={busy || models.length === 0}
                    onClick={() => void run()}
                  >
                    <Play className="h-3.5 w-3.5" />
                    {t('promptLab.run')}
                  </Button>
                </div>
                {preview !== null && (
                  <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-surface-muted p-3 font-mono text-[11px] text-ink">
                    {preview.system}
                    {preview.user ? `\n\n--- user ---\n${preview.user}` : ''}
                  </pre>
                )}
                {error !== null && <p className="mt-2 text-xs text-danger">{error}</p>}
              </div>
            </>
          )}
        </section>

        <aside className="space-y-3">
          <div className="rounded-card border border-border bg-surface p-3">
            <p className="text-sm font-medium">{t('promptLab.models')}</p>
            <div className="mt-2 max-h-48 space-y-1 overflow-y-auto">
              {choices.map((choice) => {
                const key = `${choice.provider_id}/${choice.model}`
                const active = selectedModelKeys.has(key)
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => toggleModel(choice)}
                    className={`block w-full truncate rounded px-2 py-1.5 text-left text-[11px] ${
                      active
                        ? 'bg-accent-soft text-accent'
                        : 'text-ink-muted hover:bg-surface-muted'
                    }`}
                  >
                    {choice.label}
                  </button>
                )
              })}
            </div>
          </div>
          <div className="rounded-card border border-border bg-surface">
            <p className="border-b border-border px-3 py-2 text-sm font-medium">
              {t('promptLab.history')}
            </p>
            <div className="max-h-60 divide-y divide-border overflow-y-auto">
              {(experiments.data ?? []).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => openHistory(item)}
                  className="block w-full px-3 py-2 text-left text-[11px] hover:bg-surface-muted"
                >
                  <span className="block truncate text-ink">
                    {item.system_prompt.slice(0, 60)}
                  </span>
                  <span className="text-ink-muted">
                    {item.outputs.length} models · {item.rating ?? '—'}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </aside>
      </div>

      {experiment !== null && (
        <div className="border-t border-border bg-canvas px-6 py-4">
          <div className="mx-auto max-w-7xl">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium">{t('promptLab.results')}</p>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant={experiment.rating === 'good' ? 'primary' : 'secondary'}
                  onClick={() => void rate('good')}
                >
                  {t('promptLab.good')}
                </Button>
                <Button
                  size="sm"
                  variant={experiment.rating === 'bad' ? 'primary' : 'secondary'}
                  onClick={() => void rate('bad')}
                >
                  {t('promptLab.bad')}
                </Button>
              </div>
            </div>
            <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-4">
              {experiment.outputs.map((output) => (
                <OutputColumn
                  key={output.id}
                  experiment={experiment}
                  output={output}
                  onChanged={() => {
                    void queryClient.invalidateQueries({
                      queryKey: ['prompt-experiments'],
                    })
                  }}
                />
              ))}
            </div>
          </div>
        </div>
      )}

      <Dialog
        open={diffOpen}
        onClose={() => setDiffOpen(false)}
        title={t('promptLab.diffTitle')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setDiffOpen(false)}>
              {t('common.close')}
            </Button>
            <Button size="sm" disabled={diffBusy} onClick={() => void loadDiff()}>
              <GitCompare className="h-3.5 w-3.5" />
              {t('promptLab.compare')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <PopoverSelect
              label={t('promptLab.diffFrom')}
              value={diffFrom}
              onChange={setDiffFrom}
              options={(selected?.versions ?? []).map((version) => ({
                value: String(version.version),
                label: `v${version.version}`,
              }))}
            />
            <PopoverSelect
              label={t('promptLab.diffTo')}
              value={diffTo}
              onChange={setDiffTo}
              options={(selected?.versions ?? []).map((version) => ({
                value: String(version.version),
                label: `v${version.version}`,
              }))}
            />
          </div>
          {diffError !== null && <p className="text-xs text-danger">{diffError}</p>}
          {diff !== null && (
            <div className="space-y-3">
              <p className="text-[11px] text-ink-muted">
                v{diff.from_version} → v{diff.to_version}
              </p>
              <DiffBlock title="System Prompt" lines={diff.system} />
              <DiffBlock title="User Prompt" lines={diff.user} />
            </div>
          )}
        </div>
      </Dialog>

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t('promptLab.newTemplate')}
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              disabled={busy || name.trim() === ''}
              onClick={() => void createTemplate()}
            >
              {t('common.create')}
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t('prompts.name')}
          />
          <textarea
            value={systemPrompt}
            onChange={(event) => setSystemPrompt(event.target.value)}
            placeholder="System Prompt"
            className="min-h-24 w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs"
          />
          <textarea
            value={userPrompt}
            onChange={(event) => setUserPrompt(event.target.value)}
            placeholder="User Prompt（可选）"
            className="min-h-20 w-full rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs"
          />
        </div>
      </Dialog>
    </div>
  )
}
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Download,
  Image as ImageIcon,
  Mic,
  Pencil,
  Shuffle,
  Sparkles,
  Trash2,
  Volume2,
} from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { AuthedMedia } from '../../components/media/AuthedMedia'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Input, Textarea } from '../../components/ui/input'
import { Spinner } from '../../components/ui/spinner'
import { errorMessage } from '../../lib/errors'
import { apiBlob, apiRequest, apiUpload } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  ImageAnalyzeResult,
  IntegrationConfig,
  MediaAsset,
  ModelEntry,
  PersonalModel,
} from '../../lib/types'

const IMAGE_SIZES = ['1024x1024', '512x512', '1024x1536', '1536x1024', 'auto']
const QUALITIES = ['', 'low', 'medium', 'high']
const STYLES = ['', 'natural', 'vivid']
const ANALYSIS_QUESTION = '请详细描述这张图片，并指出其中可见的文字、对象与任何异常。'

export function MultimodalPage() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const integrations = useQuery({
    queryKey: ['integrations'],
    queryFn: () => apiRequest<IntegrationConfig[]>('/integrations'),
  })
  const media = useQuery({
    queryKey: ['media-assets'],
    queryFn: () => apiRequest<MediaAsset[]>('/media?limit=50'),
  })
  const platformModels = useQuery({
    queryKey: ['models'],
    queryFn: () => apiRequest<ModelEntry[]>('/models'),
  })
  const personalModels = useQuery({
    queryKey: ['provider-configs', 'models'],
    queryFn: () => apiRequest<PersonalModel[]>('/provider-configs/models'),
  })

  const [prompt, setPrompt] = useState('')
  const [size, setSize] = useState(IMAGE_SIZES[0])
  const [quality, setQuality] = useState('')
  const [style, setStyle] = useState('')
  const [imageCount, setImageCount] = useState(1)
  const [imageIntegration, setImageIntegration] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [editAssetId, setEditAssetId] = useState<string | null>(null)
  const [editFile, setEditFile] = useState<File | null>(null)
  const [editMask, setEditMask] = useState<File | null>(null)
  const [editPrompt, setEditPrompt] = useState('')
  const [editSize, setEditSize] = useState('1024x1024')
  const [editCount, setEditCount] = useState(1)

  const [analyzeAssetId, setAnalyzeAssetId] = useState<string | null>(null)
  const [analyzeFile, setAnalyzeFile] = useState<File | null>(null)
  const [analyzeQuestion, setAnalyzeQuestion] = useState(ANALYSIS_QUESTION)
  const [analyzeModel, setAnalyzeModel] = useState('auto::auto')
  const [analysis, setAnalysis] = useState<ImageAnalyzeResult | null>(null)

  const [transcript, setTranscript] = useState('')
  const [sttIntegration, setSttIntegration] = useState('')
  const [sttFile, setSttFile] = useState<File | null>(null)
  const [ttsText, setTtsText] = useState('')
  const [ttsVoice, setTtsVoice] = useState('alloy')
  const [ttsIntegration, setTtsIntegration] = useState('')
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const audioUrlRef = useRef<string | null>(null)

  const enabled = (kind: string): IntegrationConfig[] =>
    (integrations.data ?? []).filter((item) => item.kind === kind && item.enabled)
  const imageConfigs = useMemo(() => enabled('image_generation'), [integrations.data])
  const sttConfigs = useMemo(() => enabled('stt'), [integrations.data])
  const ttsConfigs = useMemo(() => enabled('tts'), [integrations.data])
  const assets = media.data ?? []
  const editAsset = assets.find((item) => item.id === editAssetId) ?? null
  const analyzeAsset = assets.find((item) => item.id === analyzeAssetId) ?? null

  const modelChoices = useMemo(() => {
    const choices = [{ value: 'auto::auto', label: t('tasks.autoModel') }]
    for (const model of personalModels.data ?? []) {
      if (!model.capabilities.includes('vision')) continue
      choices.push({
        value: `${model.provider_id}::${model.model_id}`,
        label: `${model.display_name} · ${model.provider_name}`,
      })
    }
    for (const model of platformModels.data ?? []) {
      if (model.available && (model.tags.includes('vision') || model.tags.includes('image'))) {
        choices.push({
          value: `${model.provider_id}::${model.model_id}`,
          label: `${model.display_name} · ${model.provider_id}`,
        })
      }
    }
    return choices
  }, [personalModels.data, platformModels.data, t])

  const refreshMedia = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: ['media-assets'] })
  }

  const fileFromAsset = async (asset: MediaAsset): Promise<File> => {
    const blob = await apiBlob(asset.url)
    return new File([blob], asset.filename || `${asset.id}.png`, { type: asset.mime })
  }

  const generate = async (): Promise<void> => {
    if (prompt.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      await apiRequest<MediaAsset[]>('/images/generations', {
        method: 'POST',
        body: {
          prompt: prompt.trim(),
          size,
          n: imageCount,
          quality: quality === '' ? null : quality,
          style: style === '' ? null : style,
          integration_id: imageIntegration === '' ? null : imageIntegration,
        },
      })
      setPrompt('')
      await refreshMedia()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const editImage = async (): Promise<void> => {
    if (editPrompt.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      const source =
        editFile ?? (editAsset !== null ? await fileFromAsset(editAsset) : null)
      if (source === null) {
        setError(t('multimodal.editSourceRequired'))
        return
      }
      const form = new FormData()
      form.append('image', source)
      if (editMask !== null) form.append('mask', editMask)
      form.append('prompt', editPrompt.trim())
      form.append('size', editSize)
      form.append('n', String(editCount))
      if (quality !== '') form.append('quality', quality)
      if (style !== '') form.append('style', style)
      if (imageIntegration !== '') form.append('integration_id', imageIntegration)
      await apiUpload<MediaAsset[]>('/images/edits', form)
      setEditPrompt('')
      setEditFile(null)
      setEditMask(null)
      await refreshMedia()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const varyImage = async (asset: MediaAsset): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      const source = await fileFromAsset(asset)
      const form = new FormData()
      form.append('image', source)
      form.append('size', size)
      form.append('n', '1')
      if (imageIntegration !== '') form.append('integration_id', imageIntegration)
      await apiUpload<MediaAsset[]>('/images/variations', form)
      await refreshMedia()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const analyze = async (): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('question', analyzeQuestion.trim() || ANALYSIS_QUESTION)
      const [providerId, model] = analyzeModel.split('::')
      form.append('provider_id', providerId)
      form.append('model', model)
      if (analyzeFile !== null) {
        form.append('file', analyzeFile)
      } else if (analyzeAsset !== null) {
        form.append('media_id', analyzeAsset.id)
      } else {
        setError(t('multimodal.analyzeSourceRequired'))
        return
      }
      const result = await apiUpload<ImageAnalyzeResult>('/images/analyze', form)
      setAnalysis(result)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const download = async (asset: MediaAsset): Promise<void> => {
    const blob = await apiBlob(asset.url)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = asset.filename || `${asset.id}.png`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  }

  const removeAsset = async (asset: MediaAsset): Promise<void> => {
    setBusy(true)
    try {
      await apiRequest(`/media/${asset.id}`, { method: 'DELETE' })
      if (editAssetId === asset.id) setEditAssetId(null)
      if (analyzeAssetId === asset.id) setAnalyzeAssetId(null)
      await refreshMedia()
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const transcribe = async (): Promise<void> => {
    if (sttFile === null) return
    setBusy(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', sttFile)
      if (sttIntegration !== '') form.append('integration_id', sttIntegration)
      const result = await apiUpload<{ text: string }>('/audio/transcriptions', form)
      setTranscript(result.text)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const speak = async (): Promise<void> => {
    if (ttsText.trim() === '') return
    setBusy(true)
    setError(null)
    try {
      const blob = await apiBlob('/audio/speech', {
        method: 'POST',
        body: {
          text: ttsText.trim(),
          voice: ttsVoice,
          response_format: 'mp3',
          integration_id: ttsIntegration === '' ? null : ttsIntegration,
        },
      })
      if (audioUrlRef.current !== null) URL.revokeObjectURL(audioUrlRef.current)
      const url = URL.createObjectURL(blob)
      audioUrlRef.current = url
      setAudioUrl(url)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <header className="border-b border-border bg-surface px-6 py-4">
        <h1 className="text-lg font-semibold">{t('multimodal.title')}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t('multimodal.lead')}</p>
      </header>
      <div className="mx-auto w-full max-w-6xl space-y-6 px-6 py-6">
        {error !== null && (
          <p className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        <section className="rounded-2xl border border-border bg-surface p-4">
          <div className="flex items-center gap-2">
            <ImageIcon className="h-4 w-4 text-accent" />
            <h2 className="text-sm font-semibold">{t('multimodal.imageTitle')}</h2>
            {imageConfigs.length === 0 && (
              <Link
                to="/settings/integrations"
                className="ml-auto text-xs text-accent underline"
              >
                {t('multimodal.configure')}
              </Link>
            )}
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_150px_110px_110px_80px_auto]">
            <Textarea
              rows={2}
              value={prompt}
              placeholder={t('multimodal.imagePrompt')}
              onChange={(event) => setPrompt(event.target.value)}
            />
            <select
              className="h-10 rounded-lg border border-border bg-surface px-2 text-sm"
              value={imageIntegration}
              onChange={(event) => setImageIntegration(event.target.value)}
            >
              <option value="">{t('multimodal.defaultIntegration')}</option>
              {imageConfigs.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <select
              className="h-10 rounded-lg border border-border bg-surface px-2 text-sm"
              value={size}
              onChange={(event) => setSize(event.target.value)}
            >
              {IMAGE_SIZES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <select
              className="h-10 rounded-lg border border-border bg-surface px-2 text-sm"
              value={quality}
              onChange={(event) => setQuality(event.target.value)}
            >
              {QUALITIES.map((item) => (
                <option key={item} value={item}>
                  {item === '' ? t('multimodal.qualityDefault') : item}
                </option>
              ))}
            </select>
            <select
              className="h-10 rounded-lg border border-border bg-surface px-2 text-sm"
              value={String(imageCount)}
              onChange={(event) => setImageCount(Number(event.target.value))}
            >
              {[1, 2, 3, 4].map((item) => (
                <option key={item} value={item}>
                  × {item}
                </option>
              ))}
            </select>
            <Button disabled={busy || prompt.trim() === ''} onClick={() => void generate()}>
              <Sparkles className="h-4 w-4" />
              {t('multimodal.generate')}
            </Button>
          </div>
          <div className="mt-2 flex items-center gap-2 text-xs text-ink-muted">
            <span>{t('multimodal.style')}</span>
            <select
              className="h-8 rounded-lg border border-border bg-surface px-2 text-xs"
              value={style}
              onChange={(event) => setStyle(event.target.value)}
            >
              {STYLES.map((item) => (
                <option key={item} value={item}>
                  {item === '' ? t('multimodal.styleDefault') : item}
                </option>
              ))}
            </select>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {assets.map((asset) => (
              <figure key={asset.id} className="overflow-hidden rounded-xl border border-border">
                <AuthedMedia
                  path={asset.url}
                  alt={asset.prompt}
                  className="aspect-square w-full object-cover"
                />
                <figcaption className="space-y-1 px-2 py-1.5 text-[11px] text-ink-muted">
                  <p className="truncate">{asset.prompt || t('multimodal.variation')}</p>
                  <div className="flex items-center gap-0.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t('multimodal.edit')}
                      onClick={() => {
                        setEditAssetId(asset.id)
                        setEditFile(null)
                      }}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t('multimodal.variation')}
                      disabled={busy}
                      onClick={() => void varyImage(asset)}
                    >
                      <Shuffle className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t('multimodal.download')}
                      onClick={() => void download(asset)}
                    >
                      <Download className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto"
                      aria-label={t('common.delete')}
                      disabled={busy}
                      onClick={() => void removeAsset(asset)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </figcaption>
              </figure>
            ))}
            {assets.length === 0 && (
              <p className="text-xs text-ink-muted">{t('multimodal.noImages')}</p>
            )}
          </div>
        </section>

        <div className="grid gap-6 lg:grid-cols-2">
          <section className="rounded-2xl border border-border bg-surface p-4">
            <div className="flex items-center gap-2">
              <Pencil className="h-4 w-4 text-accent" />
              <h2 className="text-sm font-semibold">{t('multimodal.editTitle')}</h2>
            </div>
            <div className="mt-3 space-y-2">
              {editAsset !== null && (
                <div className="flex items-center gap-2 rounded-lg border border-border p-2">
                  <AuthedMedia
                    path={editAsset.url}
                    alt={editAsset.prompt}
                    className="h-12 w-12 rounded object-cover"
                  />
                  <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">
                    {editAsset.prompt}
                  </span>
                  <Button variant="ghost" size="sm" onClick={() => setEditAssetId(null)}>
                    {t('common.close')}
                  </Button>
                </div>
              )}
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="block w-full text-xs text-ink-muted"
                onChange={(event) => setEditFile(event.target.files?.[0] ?? null)}
              />
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="block w-full text-xs text-ink-muted"
                aria-label={t('multimodal.mask')}
                onChange={(event) => setEditMask(event.target.files?.[0] ?? null)}
              />
              <Textarea
                rows={3}
                value={editPrompt}
                placeholder={t('multimodal.editPrompt')}
                onChange={(event) => setEditPrompt(event.target.value)}
              />
              <div className="flex flex-wrap items-center gap-2">
                <select
                  className="h-9 rounded-lg border border-border bg-surface px-2 text-xs"
                  value={editSize}
                  onChange={(event) => setEditSize(event.target.value)}
                >
                  {IMAGE_SIZES.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
                <select
                  className="h-9 rounded-lg border border-border bg-surface px-2 text-xs"
                  value={String(editCount)}
                  onChange={(event) => setEditCount(Number(event.target.value))}
                >
                  {[1, 2, 3, 4].map((item) => (
                    <option key={item} value={item}>
                      × {item}
                    </option>
                  ))}
                </select>
                <Button
                  disabled={busy || editPrompt.trim() === ''}
                  onClick={() => void editImage()}
                >
                  {t('multimodal.applyEdit')}
                </Button>
              </div>
              <p className="text-[11px] text-ink-muted">{t('multimodal.editHint')}</p>
            </div>
          </section>

          <section className="rounded-2xl border border-border bg-surface p-4">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-accent" />
              <h2 className="text-sm font-semibold">{t('multimodal.analyzeTitle')}</h2>
            </div>
            <div className="mt-3 space-y-2">
              {analyzeAsset !== null && (
                <div className="flex items-center gap-2 rounded-lg border border-border p-2">
                  <AuthedMedia
                    path={analyzeAsset.url}
                    alt={analyzeAsset.prompt}
                    className="h-12 w-12 rounded object-cover"
                  />
                  <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">
                    {analyzeAsset.prompt}
                  </span>
                  <Button variant="ghost" size="sm" onClick={() => setAnalyzeAssetId(null)}>
                    {t('common.close')}
                  </Button>
                </div>
              )}
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="block w-full text-xs text-ink-muted"
                onChange={(event) => setAnalyzeFile(event.target.files?.[0] ?? null)}
              />
              <select
                className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-xs"
                value={analyzeModel}
                onChange={(event) => setAnalyzeModel(event.target.value)}
              >
                {modelChoices.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
              </select>
              <Textarea
                rows={2}
                value={analyzeQuestion}
                onChange={(event) => setAnalyzeQuestion(event.target.value)}
              />
              <Button disabled={busy} onClick={() => void analyze()}>
                {t('multimodal.analyze')}
              </Button>
              {analysis !== null && (
                <div className="rounded-lg border border-border bg-surface-muted p-3 text-sm">
                  <p className="whitespace-pre-wrap">{analysis.answer}</p>
                  <p className="mt-2 text-[11px] text-ink-muted">
                    {analysis.provider_id} · {analysis.model} · {analysis.prompt_tokens ?? 0}+
                    {analysis.completion_tokens ?? 0}
                  </p>
                </div>
              )}
              <p className="text-[11px] text-ink-muted">{t('multimodal.pickFromGallery')}</p>
              <div className="flex flex-wrap gap-1">
                {assets.slice(0, 8).map((asset) => (
                  <button
                    key={asset.id}
                    type="button"
                    className={`h-10 w-10 overflow-hidden rounded border ${
                      analyzeAssetId === asset.id ? 'border-accent' : 'border-border'
                    }`}
                    onClick={() => {
                      setAnalyzeAssetId(asset.id)
                      setAnalyzeFile(null)
                    }}
                  >
                    <AuthedMedia
                      path={asset.url}
                      alt={asset.prompt}
                      className="h-full w-full object-cover"
                    />
                  </button>
                ))}
              </div>
            </div>
          </section>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <section className="rounded-2xl border border-border bg-surface p-4">
            <div className="flex items-center gap-2">
              <Mic className="h-4 w-4 text-accent" />
              <h2 className="text-sm font-semibold">{t('multimodal.sttTitle')}</h2>
            </div>
            <div className="mt-3 space-y-2">
              <select
                className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm"
                value={sttIntegration}
                onChange={(event) => setSttIntegration(event.target.value)}
              >
                <option value="">{t('multimodal.defaultIntegration')}</option>
                {sttConfigs.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              <input
                type="file"
                accept=".mp3,.wav,.m4a,.webm,.ogg,.flac,.mp4"
                onChange={(event) => setSttFile(event.target.files?.[0] ?? null)}
                className="block w-full text-xs text-ink-muted"
              />
              <Button disabled={busy || sttFile === null} onClick={() => void transcribe()}>
                {t('multimodal.transcribe')}
              </Button>
              {transcript !== '' && (
                <div className="rounded-lg border border-border bg-surface-muted p-3 text-sm">
                  {transcript}
                </div>
              )}
            </div>
          </section>

          <section className="rounded-2xl border border-border bg-surface p-4">
            <div className="flex items-center gap-2">
              <Volume2 className="h-4 w-4 text-accent" />
              <h2 className="text-sm font-semibold">{t('multimodal.ttsTitle')}</h2>
            </div>
            <div className="mt-3 space-y-2">
              <select
                className="h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm"
                value={ttsIntegration}
                onChange={(event) => setTtsIntegration(event.target.value)}
              >
                <option value="">{t('multimodal.defaultIntegration')}</option>
                {ttsConfigs.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
              <Textarea
                rows={3}
                value={ttsText}
                placeholder={t('multimodal.ttsText')}
                onChange={(event) => setTtsText(event.target.value)}
              />
              <Input
                value={ttsVoice}
                placeholder={t('integrations.voice')}
                onChange={(event) => setTtsVoice(event.target.value)}
              />
              <Button disabled={busy || ttsText.trim() === ''} onClick={() => void speak()}>
                {t('multimodal.speak')}
              </Button>
              {audioUrl !== null && <audio controls src={audioUrl} className="w-full" />}
            </div>
          </section>
        </div>

        {busy && (
          <div className="flex items-center gap-2 text-xs text-ink-muted">
            <Spinner />
            {t('common.loading')}
          </div>
        )}
        <Badge tone="neutral">{t('multimodal.byok')}</Badge>
      </div>
    </div>
  )
}
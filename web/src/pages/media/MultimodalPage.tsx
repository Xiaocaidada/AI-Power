import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Image as ImageIcon, Mic, Trash2, Volume2 } from 'lucide-react'
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
import type { IntegrationConfig, MediaAsset } from '../../lib/types'

const IMAGE_SIZES = ['1024x1024', '512x512', '1024x1536', '1536x1024', 'auto']

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
  const [prompt, setPrompt] = useState('')
  const [size, setSize] = useState(IMAGE_SIZES[0])
  const [imageIntegration, setImageIntegration] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
          n: 1,
          integration_id: imageIntegration === '' ? null : imageIntegration,
        },
      })
      setPrompt('')
      await queryClient.invalidateQueries({ queryKey: ['media-assets'] })
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const removeAsset = async (asset: MediaAsset): Promise<void> => {
    setBusy(true)
    try {
      await apiRequest(`/media/${asset.id}`, { method: 'DELETE' })
      await queryClient.invalidateQueries({ queryKey: ['media-assets'] })
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

  const assets = media.data ?? []

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
          <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_160px_160px_auto]">
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
            <Button disabled={busy || prompt.trim() === ''} onClick={() => void generate()}>
              {t('multimodal.generate')}
            </Button>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {assets.map((asset) => (
              <figure key={asset.id} className="overflow-hidden rounded-xl border border-border">
                <AuthedMedia
                  path={asset.url}
                  alt={asset.prompt}
                  className="aspect-square w-full object-cover"
                />
                <figcaption className="flex items-center gap-2 px-2 py-1.5 text-[11px] text-ink-muted">
                  <span className="min-w-0 flex-1 truncate">{asset.prompt}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => void removeAsset(asset)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
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
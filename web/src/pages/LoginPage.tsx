import { Check, Sparkles } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Spinner } from '../components/ui/spinner'
import { ApiError } from '../lib/errors'
import { apiRequest, publicRequest } from '../lib/http'
import { useI18n } from '../lib/i18n'
import { setAccessToken, setRefreshToken } from '../lib/tokens'
import type { TokenResponse, User } from '../lib/types'
import { cn } from '../lib/utils'
import { useAuthStore } from '../store/auth'

type Mode = 'login' | 'register'

export function LoginPage() {
  const { t, language, setLanguage } = useI18n()
  const navigate = useNavigate()
  const location = useLocation()
  const status = useAuthStore((state) => state.status)
  const setUser = useAuthStore((state) => state.setUser)

  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [cooldown, setCooldown] = useState(0)

  useEffect(() => {
    if (cooldown <= 0) return undefined
    const timer = setTimeout(() => setCooldown((value) => value - 1), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])

  if (status === 'authenticated') return <Navigate to="/chat" replace />

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)

    if (mode === 'register') {
      if (password.length < 8) {
        setError(t('auth.passwordTooShort'))
        return
      }
      if (password !== confirmPassword) {
        setError(t('auth.passwordMismatch'))
        return
      }
    }

    setSubmitting(true)
    try {
      if (mode === 'register') {
        await publicRequest('/auth/register', {
          method: 'POST',
          body: { email, password },
        })
      }
      const tokens = await publicRequest<TokenResponse>('/auth/login', {
        method: 'POST',
        body: { email, password },
      })
      setAccessToken(tokens.access_token)
      setRefreshToken(tokens.refresh_token)
      const user = await apiRequest<User>('/auth/me')
      setUser(user)
      const from = (location.state as { from?: string } | null)?.from
      navigate(from ?? '/chat', { replace: true })
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 429) {
        const seconds = caught.retryAfter ?? 60
        setCooldown(seconds)
        setError(t('auth.rateLimited', { seconds }))
      } else if (caught instanceof ApiError && caught.status === 401) {
        setError(t('auth.invalidCredentials'))
      } else if (caught instanceof ApiError && caught.status === 409) {
        setError(caught.message)
      } else {
        setError(t('auth.networkError'))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-dvh bg-canvas">
      <aside className="hidden w-5/12 max-w-xl flex-col justify-between border-r border-border bg-surface p-12 lg:flex">
        <div className="flex items-center gap-2 text-sm font-medium text-ink">
          <Sparkles className="h-4 w-4 text-accent" />
          {t('common.appName')}
        </div>
        <div>
          <h1 className="font-serif text-4xl leading-tight text-ink">{t('auth.brandTitle')}</h1>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-ink-muted">
            {t('auth.brandLead')}
          </p>
          <ul className="mt-8 space-y-3 text-sm text-ink-muted">
            {(['point1', 'point2', 'point3'] as const).map((key) => (
              <li key={key} className="flex items-center gap-2">
                <Check className="h-4 w-4 text-accent" />
                {t(`auth.${key}`)}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs text-ink-muted">192.168.29.100</p>
      </aside>

      <main className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <div className="mb-6 flex rounded-lg bg-surface-muted p-1">
            {(['login', 'register'] as const).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => {
                  setMode(item)
                  setError(null)
                }}
                className={cn(
                  'flex-1 rounded-md py-1.5 text-sm transition-colors',
                  mode === item
                    ? 'bg-surface font-medium text-ink shadow-subtle'
                    : 'text-ink-muted',
                )}
              >
                {t(`auth.${item}`)}
              </button>
            ))}
          </div>

          <form className="space-y-4" onSubmit={(event) => void submit(event)}>
            <label className="block text-sm">
              <span className="mb-1.5 block text-ink-muted">{t('auth.email')}</span>
              <Input
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1.5 block text-ink-muted">{t('auth.password')}</span>
              <Input
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                required
                minLength={mode === 'register' ? 8 : 1}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {mode === 'register' && (
              <label className="block text-sm">
                <span className="mb-1.5 block text-ink-muted">{t('auth.confirmPassword')}</span>
                <Input
                  type="password"
                  autoComplete="new-password"
                  required
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                />
              </label>
            )}

            {error !== null && (
              <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
                {error}
              </p>
            )}

            <Button type="submit" className="w-full" disabled={submitting || cooldown > 0}>
              {submitting && <Spinner />}
              {submitting
                ? t('auth.loading')
                : cooldown > 0
                  ? t('auth.rateLimited', { seconds: cooldown })
                  : mode === 'login'
                    ? t('auth.signIn')
                    : t('auth.signUp')}
            </Button>
          </form>

          <div className="mt-8 flex items-center justify-center gap-2 text-xs text-ink-muted">
            <span>{t('common.language')}</span>
            <button
              type="button"
              className={cn('rounded px-1.5 py-0.5', language === 'zh' && 'text-ink underline')}
              onClick={() => setLanguage('zh')}
            >
              {t('common.chinese')}
            </button>
            <button
              type="button"
              className={cn('rounded px-1.5 py-0.5', language === 'en' && 'text-ink underline')}
              onClick={() => setLanguage('en')}
            >
              {t('common.english')}
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
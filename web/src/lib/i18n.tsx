import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { en } from '../locales/en'
import { zh } from '../locales/zh'

export type Language = 'zh' | 'en'

const STORAGE_KEY = 'ai_power_language'
const dictionaries: Record<Language, unknown> = { zh, en }

interface I18nValue {
  language: Language
  setLanguage: (language: Language) => void
  t: (key: string, vars?: Record<string, string | number>) => string
}

const I18nContext = createContext<I18nValue | null>(null)

function readKey(dictionary: unknown, path: string): string | undefined {
  const value = path.split('.').reduce<unknown>((node, part) => {
    if (node !== null && typeof node === 'object' && part in node) {
      return (node as Record<string, unknown>)[part]
    }
    return undefined
  }, dictionary)
  return typeof value === 'string' ? value : undefined
}

function initialLanguage(): Language {
  return localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'zh'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(initialLanguage)

  useEffect(() => {
    document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en'
    localStorage.setItem(STORAGE_KEY, language)
  }, [language])

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => {
      const template = readKey(dictionaries[language], key) ?? readKey(zh, key) ?? key
      if (!vars) return template
      return template.replace(/\{(\w+)\}/g, (match, name: string) =>
        vars[name] === undefined ? match : String(vars[name]),
      )
    },
    [language],
  )

  const value = useMemo(() => ({ language, setLanguage, t }), [language, t])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const context = useContext(I18nContext)
  if (context === null) throw new Error('useI18n must be used inside I18nProvider')
  return context
}
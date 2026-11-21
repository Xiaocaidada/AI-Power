const BYTE_UNITS = ['KB', 'MB', 'GB'] as const

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  const formatted = new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(value)
  return `${formatted} ${BYTE_UNITS[unit]}`
}

export function formatDate(value: string, language: 'zh' | 'en'): string {
  return new Intl.DateTimeFormat(language === 'zh' ? 'zh-CN' : 'en', {
    dateStyle: 'medium',
  }).format(new Date(value))
}
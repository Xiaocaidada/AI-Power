import { Brain } from 'lucide-react'

import {
  PopoverSelect,
  type PopoverSelectOption,
} from '../../components/ui/popover-select'
import { thinkingLabelKey } from '../../lib/chatModes'
import { useI18n } from '../../lib/i18n'
import type { ThinkingLevel, ThinkingLevelSpec } from '../../lib/types'

interface ThinkingSelectProps {
  value: ThinkingLevel
  supported: ThinkingLevel[]
  specs?: ThinkingLevelSpec[]
  disabled?: boolean
  onChange: (level: ThinkingLevel) => void
}

export function ThinkingSelect({
  value,
  supported,
  specs = [],
  disabled = false,
  onChange,
}: ThinkingSelectProps) {
  const { t } = useI18n()
  const levels = supported.length > 0 ? supported : ['standard']
  const current = levels.includes(value) ? value : levels[0]
  const labelFor = (level: string): string => {
    const configured = specs.find((item) => item.id === level)?.label
    if (configured !== undefined && configured !== '') return configured
    const key = thinkingLabelKey(level)
    return key === null ? level : t(key)
  }
  const options: PopoverSelectOption[] = levels.map((level) => ({
    value: level,
    label: labelFor(level),
  }))

  return (
    <PopoverSelect
      icon={<Brain className="h-3.5 w-3.5" />}
      label={t('chat.thinkingLevel')}
      value={current}
      options={options}
      onChange={(next) => onChange(next)}
      disabled={disabled}
      variant="ghost"
      placement="top"
    />
  )
}
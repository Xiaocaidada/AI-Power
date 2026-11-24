import { Brain } from 'lucide-react'

import {
  PopoverSelect,
  type PopoverSelectOption,
} from '../../components/ui/popover-select'
import {
  THINKING_LEVELS,
  thinkingLabelKey,
} from '../../lib/chatModes'
import { useI18n } from '../../lib/i18n'
import type { ThinkingLevel } from '../../lib/types'

interface ThinkingSelectProps {
  value: ThinkingLevel
  supported: ThinkingLevel[]
  disabled?: boolean
  onChange: (level: ThinkingLevel) => void
}

export function ThinkingSelect({
  value,
  supported,
  disabled = false,
  onChange,
}: ThinkingSelectProps) {
  const { t } = useI18n()
  const current = supported.includes(value) ? value : 'standard'
  const options: PopoverSelectOption[] = THINKING_LEVELS.map((level) => ({
    value: level,
    label: t(thinkingLabelKey(level)),
    trailing: supported.includes(level) ? undefined : t('chat.thinkingUnsupported'),
    disabled: !supported.includes(level),
  }))

  return (
    <PopoverSelect
      icon={<Brain className="h-3.5 w-3.5" />}
      label={t('chat.thinkingLevel')}
      value={current}
      options={options}
      onChange={(next) => onChange(next as ThinkingLevel)}
      disabled={disabled}
      variant="ghost"
      placement="top"
    />
  )
}
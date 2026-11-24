import { Compass } from 'lucide-react'

import {
  PopoverSelect,
  type PopoverSelectOption,
} from '../../components/ui/popover-select'
import { CHAT_MODES, modeHintKey, modeLabelKey } from '../../lib/chatModes'
import { useI18n } from '../../lib/i18n'
import type { ChatMode, ChatModesResponse } from '../../lib/types'
import { isModeImplemented } from '../../lib/useChatModes'

interface ModeSelectorProps {
  value: ChatMode
  onChange: (mode: ChatMode) => void
  catalog?: ChatModesResponse
  disabled?: boolean
  variant?: 'chip' | 'ghost'
  placement?: 'top' | 'bottom'
}

export function ModeSelector({
  value,
  onChange,
  catalog,
  disabled = false,
  variant = 'chip',
  placement = 'bottom',
}: ModeSelectorProps) {
  const { t } = useI18n()
  const options: PopoverSelectOption[] = CHAT_MODES.map((mode) => {
    const implemented = isModeImplemented(mode, catalog)
    return {
      value: mode,
      label: t(modeLabelKey(mode)),
      description: t(modeHintKey(mode)),
      trailing: implemented ? undefined : t('chat.modePlanned'),
    }
  })
  return (
    <PopoverSelect
      icon={<Compass className="h-3.5 w-3.5" />}
      label={t('chat.mode')}
      value={value}
      options={options}
      onChange={(next) => onChange(next as ChatMode)}
      disabled={disabled}
      variant={variant}
      placement={placement}
    />
  )
}
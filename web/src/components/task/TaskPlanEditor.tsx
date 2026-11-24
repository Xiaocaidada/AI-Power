import { Plus, Trash2 } from 'lucide-react'

import { useI18n } from '../../lib/i18n'
import { Button } from '../ui/button'
import { Input } from '../ui/input'

export interface EditableTaskStep {
  title: string
  detail: string
  query: string
}

interface TaskPlanEditorProps {
  steps: EditableTaskStep[]
  disabled: boolean
  showQuery?: boolean
  onChange: (steps: EditableTaskStep[]) => void
}

export function TaskPlanEditor({
  steps,
  disabled,
  showQuery = false,
  onChange,
}: TaskPlanEditorProps) {
  const { t } = useI18n()

  const update = (index: number, patch: Partial<EditableTaskStep>): void => {
    onChange(steps.map((step, position) => (position === index ? { ...step, ...patch } : step)))
  }

  return (
    <div className="space-y-2">
      {steps.map((step, index) => (
        <div key={index} className="rounded-xl border border-border bg-surface p-3">
          <div className="flex items-start gap-2">
            <span className="mt-2 w-5 text-right text-xs text-ink-muted">{index + 1}</span>
            <div className="flex-1 space-y-2">
              <Input
                value={step.title}
                disabled={disabled}
                aria-label={t('tasks.stepTitle')}
                placeholder={t('tasks.stepTitle')}
                onChange={(event) => update(index, { title: event.target.value })}
              />
              {showQuery ? (
                <Input
                  value={step.query}
                  disabled={disabled}
                  aria-label={t('tasks.stepQuery')}
                  placeholder={t('tasks.stepQuery')}
                  onChange={(event) => update(index, { query: event.target.value })}
                />
              ) : (
                <Input
                  value={step.detail}
                  disabled={disabled}
                  aria-label={t('tasks.stepDetail')}
                  placeholder={t('tasks.stepDetail')}
                  onChange={(event) => update(index, { detail: event.target.value })}
                />
              )}
            </div>
            <Button
              variant="ghost"
              size="sm"
              disabled={disabled || steps.length <= 1}
              aria-label={t('tasks.removeStep')}
              onClick={() => onChange(steps.filter((_, position) => position !== index))}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      ))}
      <Button
        variant="secondary"
        size="sm"
        disabled={disabled}
        onClick={() => onChange([...steps, { title: '', detail: '', query: '' }])}
      >
        <Plus className="h-4 w-4" />
        {t('tasks.addStep')}
      </Button>
    </div>
  )
}
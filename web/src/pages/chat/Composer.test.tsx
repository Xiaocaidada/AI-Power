import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../lib/i18n'
import { Composer } from './Composer'

describe('Composer', () => {
  it('sends on Enter but not on Shift+Enter', async () => {
    const onSend = vi.fn().mockResolvedValue(undefined)
    render(
      <I18nProvider>
        <Composer value="你好" onValueChange={vi.fn()} onSend={onSend} />
      </I18nProvider>,
    )
    const textarea = screen.getByRole('textbox')

    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true })
    expect(onSend).not.toHaveBeenCalled()

    await act(async () => {
      fireEvent.keyDown(textarea, { key: 'Enter' })
    })
    expect(onSend).toHaveBeenCalledWith('你好')
  })

  it('does not send whitespace-only input', () => {
    const onSend = vi.fn().mockResolvedValue(undefined)
    render(
      <I18nProvider>
        <Composer value="   " onValueChange={vi.fn()} onSend={onSend} />
      </I18nProvider>,
    )

    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
    })

    expect(onSend).not.toHaveBeenCalled()
  })
})
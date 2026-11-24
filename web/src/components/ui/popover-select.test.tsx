import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PopoverSelect, type PopoverSelectOption } from './popover-select'

const options: PopoverSelectOption[] = [
  { value: '', label: '不使用项目' },
  { value: 'p-1', label: '产品规划', group: '项目', trailing: '6' },
  { value: 'p-2', label: '知识库工程', group: '项目' },
]

describe('PopoverSelect', () => {
  it('opens, selects an option and closes', () => {
    const onChange = vi.fn()
    render(
      <PopoverSelect label="项目" value="" options={options} onChange={onChange} />,
    )

    fireEvent.click(screen.getByRole('button', { name: '项目: 不使用项目' }))
    expect(screen.getByRole('listbox', { name: '项目' })).toBeTruthy()

    fireEvent.click(screen.getByRole('option', { name: /产品规划/ }))
    expect(onChange).toHaveBeenCalledWith('p-1')
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('opens with the keyboard and closes on Escape', () => {
    render(
      <PopoverSelect label="项目" value="" options={options} onChange={vi.fn()} />,
    )

    fireEvent.keyDown(screen.getByRole('button', { name: '项目: 不使用项目' }), {
      key: 'ArrowDown',
    })
    const listbox = screen.getByRole('listbox', { name: '项目' })
    expect(listbox).toBeTruthy()

    fireEvent.keyDown(listbox, { key: 'Escape' })
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('marks the current value as selected', () => {
    render(
      <PopoverSelect label="项目" value="p-2" options={options} onChange={vi.fn()} />,
    )

    fireEvent.click(screen.getByRole('button', { name: '项目: 知识库工程' }))
    expect(
      screen.getByRole('option', { name: /知识库工程/ }).getAttribute('aria-selected'),
    ).toBe('true')
  })

  it('does not select a disabled option', () => {
    const onChange = vi.fn()
    render(
      <PopoverSelect
        label="思考等级"
        value="standard"
        options={[
          { value: 'fast', label: '快速', disabled: true },
          { value: 'standard', label: '标准' },
        ]}
        onChange={onChange}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '思考等级: 标准' }))
    const fast = screen.getByRole('option', { name: '快速' })
    expect(fast.getAttribute('aria-disabled')).toBe('true')
    fireEvent.click(fast)
    expect(onChange).not.toHaveBeenCalled()
  })
})
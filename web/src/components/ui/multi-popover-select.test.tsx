import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { MultiPopoverSelect } from './multi-popover-select'

const options = [
  { value: 'kb-1', label: '产品资料库' },
  { value: 'kb-2', label: '工程文档' },
]

describe('MultiPopoverSelect', () => {
  it('toggles multiple values without closing the panel', () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <MultiPopoverSelect
        label="知识库"
        values={[]}
        options={options}
        onChange={onChange}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '知识库: 知识库' }))
    fireEvent.click(screen.getByRole('option', { name: '产品资料库' }))
    expect(onChange).toHaveBeenCalledWith(['kb-1'])

    rerender(
      <MultiPopoverSelect
        label="知识库"
        values={['kb-1']}
        options={options}
        onChange={onChange}
      />,
    )
    expect(screen.getByRole('listbox', { name: '知识库' })).toBeTruthy()
    fireEvent.click(screen.getByRole('option', { name: '工程文档' }))
    expect(onChange).toHaveBeenLastCalledWith(['kb-1', 'kb-2'])
  })

  it('summarizes the selection', () => {
    render(
      <MultiPopoverSelect
        label="知识库"
        values={['kb-1', 'kb-2']}
        options={options}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: '知识库: 产品资料库 +1' })).toBeTruthy()
  })

  it('shows an empty state when no options exist', () => {
    render(
      <MultiPopoverSelect
        label="知识库"
        values={[]}
        options={[]}
        onChange={vi.fn()}
        emptyLabel="还没有知识库"
        emptyAction={<span>新建知识库</span>}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '知识库: 知识库' }))
    expect(screen.getByText('还没有知识库')).toBeTruthy()
    expect(screen.getByText('新建知识库')).toBeTruthy()
  })
})
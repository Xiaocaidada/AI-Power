import { describe, expect, test } from 'vitest'

import {
  emptyHistory,
  recordHistory,
  redoHistory,
  undoHistory,
} from './canvasHistory'

describe('canvas history', () => {
  test('records and undoes previous definitions', () => {
    let history = emptyHistory<string>()
    history = recordHistory(history, 'a')
    history = recordHistory(history, 'b')

    const undone = undoHistory(history, 'c')
    expect(undone?.value).toBe('b')
    expect(undone?.history.past).toEqual(['a'])
    expect(undone?.history.future).toEqual(['c'])
  })

  test('redo restores the undone definition', () => {
    let history = emptyHistory<string>()
    history = recordHistory(history, 'a')
    const undone = undoHistory(history, 'b')
    expect(undone).not.toBeNull()
    const redone = redoHistory(undone!.history, undone!.value)
    expect(redone?.value).toBe('b')
    expect(redone?.history.future).toEqual([])
  })

  test('returns null when there is nothing to undo or redo', () => {
    expect(undoHistory(emptyHistory<string>(), 'a')).toBeNull()
    expect(redoHistory(emptyHistory<string>(), 'a')).toBeNull()
  })

  test('caps history length', () => {
    let history = emptyHistory<number>()
    for (let index = 0; index < 60; index += 1) {
      history = recordHistory(history, index, 10)
    }
    expect(history.past).toHaveLength(10)
    expect(history.past[history.past.length - 1]).toBe(59)
  })
})
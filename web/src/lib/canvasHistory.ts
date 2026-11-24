export interface CanvasHistory<T> {
  past: T[]
  future: T[]
}

export function emptyHistory<T>(): CanvasHistory<T> {
  return { past: [], future: [] }
}

export function recordHistory<T>(
  history: CanvasHistory<T>,
  current: T,
  limit = 50,
): CanvasHistory<T> {
  return {
    past: [...history.past.slice(-(limit - 1)), current],
    future: [],
  }
}

export function undoHistory<T>(
  history: CanvasHistory<T>,
  current: T,
): { history: CanvasHistory<T>; value: T } | null {
  const value = history.past[history.past.length - 1]
  if (value === undefined) return null
  return {
    history: {
      past: history.past.slice(0, -1),
      future: [current, ...history.future].slice(0, 50),
    },
    value,
  }
}

export function redoHistory<T>(
  history: CanvasHistory<T>,
  current: T,
): { history: CanvasHistory<T>; value: T } | null {
  const value = history.future[0]
  if (value === undefined) return null
  return {
    history: {
      past: [...history.past, current].slice(-50),
      future: history.future.slice(1),
    },
    value,
  }
}
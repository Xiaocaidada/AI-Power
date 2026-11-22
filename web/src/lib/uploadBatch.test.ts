import { describe, expect, it } from 'vitest'

import { createUploadTasks, MAX_UPLOAD_BYTES, validateUploadFile } from './uploadBatch'

function file(name: string, size = 10): File {
  return new File([new Uint8Array(size)], name)
}

describe('upload batch helpers', () => {
  it('accepts supported extensions and rejects others', () => {
    expect(validateUploadFile(file('guide.PDF'))).toBeNull()
    expect(validateUploadFile(file('notes.md'))).toBeNull()
    expect(validateUploadFile(file('data.txt'))).toBeNull()
    expect(validateUploadFile(file('image.png'))).toBe('errors.unsupportedType')
  })

  it('marks oversized files as failed and keeps valid files uploading', () => {
    const tasks = createUploadTasks([
      file('ok.md'),
      file('large.pdf', MAX_UPLOAD_BYTES + 1),
      file('bad.exe'),
    ])

    expect(tasks.map((task) => task.status)).toEqual(['uploading', 'failed', 'failed'])
    expect(tasks[1].errorKey).toBe('errors.tooLarge')
    expect(tasks[2].errorKey).toBe('errors.unsupportedType')
    expect(tasks.every((task) => task.percent === 0)).toBe(true)
  })
})
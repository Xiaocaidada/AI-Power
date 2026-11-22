export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024
export const ALLOWED_EXTENSIONS = ['.pdf', '.md', '.txt'] as const

export type UploadTaskStatus = 'uploading' | 'ready' | 'duplicate' | 'failed'

export interface UploadTask {
  id: string
  name: string
  percent: number
  status: UploadTaskStatus
  errorKey?: string
}

let nextTaskId = 0

export function validateUploadFile(file: File): string | null {
  const name = file.name.toLowerCase()
  if (!ALLOWED_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return 'errors.unsupportedType'
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return 'errors.tooLarge'
  }
  return null
}

export function createUploadTasks(files: File[]): UploadTask[] {
  return files.map((file) => {
    nextTaskId += 1
    const errorKey = validateUploadFile(file)
    return {
      id: `upload-${nextTaskId}`,
      name: file.name,
      percent: 0,
      status: errorKey === null ? 'uploading' : 'failed',
      errorKey: errorKey ?? undefined,
    }
  })
}
import { API_BASE } from './config'
import { ApiError, apiErrorFromPayload } from './errors'
import { getAccessToken, refreshAccessToken } from './tokens'
import type { DocumentUpload } from './types'

export interface UploadOptions {
  kbId: string
  file: File
  onProgress?: (percent: number) => void
  signal?: AbortSignal
}

function send({ kbId, file, onProgress, signal }: UploadOptions): Promise<DocumentUpload> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}/knowledge-bases/${kbId}/documents`)
    const token = getAccessToken()
    if (token !== null) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress?.(Math.round((event.loaded / event.total) * 100))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'Network error'))
    xhr.onabort = () => reject(new ApiError(0, 'Upload aborted'))
    xhr.onload = () => {
      let body: unknown = null
      try {
        body = JSON.parse(xhr.responseText) as unknown
      } catch {
        body = null
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as DocumentUpload)
      } else {
        reject(apiErrorFromPayload(xhr.status, body, xhr.getResponseHeader('Retry-After')))
      }
    }

    if (signal !== undefined) {
      signal.addEventListener('abort', () => xhr.abort(), { once: true })
    }

    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}

export async function uploadDocument(options: UploadOptions): Promise<DocumentUpload> {
  try {
    return await send(options)
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      await refreshAccessToken()
      return send(options)
    }
    throw error
  }
}
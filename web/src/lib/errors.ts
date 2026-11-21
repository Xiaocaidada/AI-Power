export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly retryAfter?: number

  constructor(status: number, message: string, code?: string, retryAfter?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.retryAfter = retryAfter
  }
}

interface DetailShape {
  code?: unknown
  message?: unknown
}

function asDetail(body: unknown): DetailShape | null {
  if (body === null || typeof body !== 'object' || !('detail' in body)) return null
  const detail = (body as { detail: unknown }).detail
  if (typeof detail === 'string') return { message: detail }
  if (detail !== null && typeof detail === 'object') return detail as DetailShape
  return null
}

export async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    body = null
  }
  const detail = asDetail(body)
  const code = typeof detail?.code === 'string' ? detail.code : undefined
  const message =
    typeof detail?.message === 'string' && detail.message.length > 0
      ? detail.message
      : response.statusText || `HTTP ${response.status}`
  const retryAfterHeader = response.headers.get('Retry-After')
  const retryAfter = retryAfterHeader !== null ? Number(retryAfterHeader) : undefined
  return new ApiError(
    response.status,
    message,
    code,
    Number.isFinite(retryAfter) ? retryAfter : undefined,
  )
}

export function apiErrorCode(error: unknown): string | undefined {
  return error instanceof ApiError ? error.code : undefined
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Unexpected error'
}
import { ApiError } from './errors'

export function errorTextKey(error: unknown): string {
  if (!(error instanceof ApiError)) return 'errors.network'
  if (error.code === 'retrieval_failed') return 'errors.retrievalFailed'
  if (error.code === 'queue_unavailable') return 'errors.queueUnavailable'
  if (error.code === 'question_in_use') return 'errors.questionInUse'
  switch (error.status) {
    case 401:
      return 'errors.unauthorized'
    case 403:
      return 'errors.forbidden'
    case 404:
      return 'errors.notFound'
    case 409:
      return 'errors.conflict'
    case 413:
      return 'errors.tooLarge'
    case 415:
      return 'errors.unsupportedType'
    case 429:
      return 'errors.rateLimited'
    case 502:
      return 'errors.retrievalFailed'
    case 503:
      return 'errors.queueUnavailable'
    default:
      return 'errors.generic'
  }
}
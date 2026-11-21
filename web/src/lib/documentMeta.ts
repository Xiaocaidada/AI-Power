import type { DocumentItem } from './types'

export type DocumentTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger'

const STATUS_KEYS: Record<string, string> = {
  uploaded: 'documents.status.uploaded',
  parsing: 'documents.status.parsing',
  embedding: 'documents.status.embedding',
  ready: 'documents.status.ready',
  failed: 'documents.status.failed',
}

const STATUS_TONES: Record<string, DocumentTone> = {
  uploaded: 'accent',
  parsing: 'accent',
  embedding: 'accent',
  ready: 'success',
  failed: 'danger',
}

const PROCESSING = new Set(['uploaded', 'parsing', 'embedding'])

const KNOWN_ERRORS = new Set([
  'too_many_pages',
  'empty_document',
  'embedding_failed',
  'embedding_count_mismatch',
  'embedding_dimension_mismatch',
  'ingestion_failed',
  'queue_unavailable',
  'parse_failed',
])

export function documentStatusKey(status: string): string {
  return STATUS_KEYS[status] ?? 'documents.status.unknown'
}

export function documentStatusTone(status: string): DocumentTone {
  return STATUS_TONES[status] ?? 'neutral'
}

export function documentIsProcessing(status: string): boolean {
  return PROCESSING.has(status)
}

export function shouldPollDocuments(documents: DocumentItem[] | undefined): boolean {
  return (documents ?? []).some((document) => PROCESSING.has(document.status))
}

export function documentErrorKey(code: string): string {
  return KNOWN_ERRORS.has(code) ? `documents.errors.${code}` : 'documents.errors.unknown'
}
import { describe, expect, it } from 'vitest'

import {
  documentErrorKey,
  documentStatusKey,
  documentStatusTone,
  shouldPollDocuments,
} from './documentMeta'
import type { DocumentItem } from './types'

function doc(partial: Partial<DocumentItem>): DocumentItem {
  return {
    id: 'doc-1',
    filename: 'note.txt',
    mime: 'text/plain',
    size_bytes: 10,
    status: 'ready',
    error_code: null,
    page_count: 1,
    created_at: '2026-11-21T00:00:00Z',
    ...partial,
  }
}

describe('documentMeta', () => {
  it('maps statuses to i18n keys and badge tones', () => {
    expect(documentStatusKey('ready')).toBe('documents.status.ready')
    expect(documentStatusKey('failed')).toBe('documents.status.failed')
    expect(documentStatusKey('weird')).toBe('documents.status.unknown')

    expect(documentStatusTone('ready')).toBe('success')
    expect(documentStatusTone('failed')).toBe('danger')
    expect(documentStatusTone('embedding')).toBe('accent')
    expect(documentStatusTone('weird')).toBe('neutral')
  })

  it('polls only while documents are processing', () => {
    expect(shouldPollDocuments(undefined)).toBe(false)
    expect(shouldPollDocuments([])).toBe(false)
    expect(shouldPollDocuments([doc({ status: 'ready' })])).toBe(false)
    expect(shouldPollDocuments([doc({ status: 'ready' }), doc({ status: 'parsing' })])).toBe(true)
    expect(shouldPollDocuments([doc({ status: 'uploaded' })])).toBe(true)
  })

  it('maps known ingestion errors and falls back for unknown codes', () => {
    expect(documentErrorKey('empty_document')).toBe('documents.errors.empty_document')
    expect(documentErrorKey('queue_unavailable')).toBe('documents.errors.queue_unavailable')
    expect(documentErrorKey('custom_failure')).toBe('documents.errors.unknown')
  })
})
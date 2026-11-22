import { apiDownload } from './http'

export type ConversationExportFormat = 'markdown' | 'json'

const EXTENSIONS: Record<ConversationExportFormat, string> = {
  markdown: 'md',
  json: 'json',
}

export async function downloadConversationExport(
  conversationId: string,
  format: ConversationExportFormat,
): Promise<void> {
  const { blob, filename } = await apiDownload(
    `/conversations/${conversationId}/export?format=${format}`,
  )
  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download =
      filename ?? `conversation-${conversationId}.${EXTENSIONS[format]}`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}
import { apiDownload, apiUpload } from './http'
import type { ChatAttachment } from './types'

export const ATTACHMENT_ACCEPT = '.pdf,.md,.txt,.docx,.csv,.png,.jpg,.jpeg,.webp'

export async function uploadChatAttachment(
  file: File,
  conversationId?: string,
): Promise<ChatAttachment> {
  const form = new FormData()
  form.append('file', file)
  if (conversationId !== undefined) form.append('conversation_id', conversationId)
  return apiUpload<ChatAttachment>('/attachments', form)
}

export async function downloadChatAttachment(
  attachment: ChatAttachment,
): Promise<void> {
  const result = await apiDownload(`/attachments/${attachment.id}/download`)
  const url = URL.createObjectURL(result.blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = result.filename ?? attachment.filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
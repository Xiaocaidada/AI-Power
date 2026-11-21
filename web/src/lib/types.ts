export interface User {
  id: string
  email: string
  role: string
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  refresh_token: string
  refresh_expires_in: number
}

export interface Provider {
  id: string
  available: boolean
  models: string[]
}

export interface KnowledgeBase {
  id: string
  name: string
  created_at: string
}

export interface Conversation {
  id: string
  title: string
  provider_id: string
  model: string
  kb_id: string | null
  created_at: string
}

export interface Citation {
  index: number
  document_id: string
  chunk_id: string
  page_no: number | null
  snippet: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  status: string
  provider_id: string | null
  model: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  created_at: string
  citations: Citation[]
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
}

export interface ChatUsage {
  prompt_tokens: number | null
  completion_tokens: number | null
}

export interface DocumentItem {
  id: string
  filename: string
  mime: string
  size_bytes: number
  status: string
  error_code: string | null
  page_count: number | null
  created_at: string
}

export interface DocumentUpload {
  id: string
  status: string
  duplicate: boolean
}

export interface UsageBucket {
  key: string
  requests: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface UsageSummary {
  start: string
  end: string
  group_by: string
  buckets: UsageBucket[]
}

export interface ApiKeyRecord {
  id: string
  name: string
  prefix: string
  scopes: string[]
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export interface ApiKeyCreated extends ApiKeyRecord {
  key: string
}

export interface SseMeta {
  message_id: string
  provider: string
  model: string
  conversation_id: string
}

export interface SseError {
  code: string
  message: string
}
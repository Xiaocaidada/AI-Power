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
  agent: boolean
  created_at: string
}

export interface AgentActivity {
  id: string
  type: 'agent_start' | 'agent_end' | 'tool_call' | 'tool_result'
  agent: string
  depth: number
  tool?: string
  arguments?: Record<string, unknown>
  ok?: boolean
  output?: string
  error_code?: string | null
  duration_ms?: number
  status?: string
}

export interface AgentTraceStep {
  agent: string
  tool: string
  ok: boolean
  duration_ms: number
  depth?: number
  target?: string
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
  request_id?: string | null
  created_at: string
  citations: Citation[]
}

export interface WorkspaceItem {
  id: string
  name: string
  plan: string
  is_personal: boolean
  role: string
  created_at: string
}

export interface WorkspaceMember {
  user_id: string
  email: string
  role: string
  created_at: string
}

export interface ModelEntry {
  id: string
  provider_id: string
  model_id: string
  display_name: string
  context_window: number
  input_price: number
  output_price: number
  tags: string[]
  priority: number
  available: boolean
}

export interface QuotaWindow {
  limit: number
  used: number
  remaining: number
  reset_seconds: number
}

export interface QuotaSummary {
  plan: string
  requests: QuotaWindow
  tokens: QuotaWindow
  max_keys: number
  active_keys: number
}

export interface TraceRecord {
  id?: string
  request_id: string
  conversation_id: string | null
  message_id: string | null
  provider_id: string | null
  model: string | null
  retrieval_ms: number | null
  ttft_ms: number | null
  total_ms: number | null
  status: string
  error_code: string | null
  attempts: number
  agents?: AgentTraceStep[] | null
  created_at: string
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
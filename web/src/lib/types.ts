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

export interface MarketModel {
  id: string
  slug: string
  name: string
  provider_id: string
  provider_name: string
  model_id: string
  description: string
  category: string
  capabilities: string[]
  input_types: string[]
  output_types: string[]
  context_window: number
  max_output: number | null
  logo_url: string
  docs_url: string
  featured: boolean
  is_new: boolean
  sort_order: number
  enabled: boolean
  available: boolean
}

export type PlacementKind = 'banner' | 'featured' | 'activity'

export interface HomePlacement {
  id: string
  kind: PlacementKind
  title: string
  subtitle: string
  body: string
  image_url: string
  link_url: string
  link_label: string
  sort_order: number
  enabled: boolean
  starts_at: string | null
  ends_at: string | null
  created_at: string
  updated_at: string
}

export type AnnouncementCategory = 'notice' | 'update' | 'event' | 'maintenance'
export type AnnouncementStatus = 'draft' | 'published' | 'archived'

export interface Announcement {
  id: string
  title: string
  summary: string
  body: string
  cover_url: string
  category: AnnouncementCategory
  pinned: boolean
  status: AnnouncementStatus
  published_at: string | null
  expires_at: string | null
  created_at: string
  updated_at: string
}

export interface HomeFeed {
  banners: HomePlacement[]
  featured: HomePlacement[]
  activities: HomePlacement[]
  announcements: Announcement[]
}

export interface NotificationItem extends Announcement {
  read_at: string | null
}

export interface NotificationFeed {
  unread_count: number
  items: NotificationItem[]
}

export interface ProviderConfig {
  id: string
  name: string
  provider_type: string
  base_url: string
  api_key_hint: string
  note: string
  shared: boolean
  owned: boolean
  status: string
  last_error: string | null
  last_tested_at: string | null
  model_count: number
  created_at: string
  updated_at: string
}

export interface ProviderModel {
  id: string
  model_id: string
  display_name: string
  capabilities: string[]
  source: string
  enabled: boolean
}

export interface PersonalModel {
  provider_id: string
  provider_name: string
  model_id: string
  display_name: string
  capabilities: string[]
}

export interface ProviderTestResult {
  status: string
  model_count: number
  error_code: string | null
}

export interface ProviderSyncResult {
  added: number
  updated: number
  total: number
}

export interface KnowledgeBase {
  id: string
  name: string
  created_at: string
}

export interface KnowledgeBaseSettings {
  chunking: {
    chunk_size: number
    chunk_overlap: number
  }
  retrieval: {
    top_k: number
    candidate_k: number
    hybrid_enabled: boolean
    rerank_enabled: boolean
  }
  embedding: {
    provider_config_id: string | null
    model: string | null
    dimensions: number
  }
  rerank: {
    provider_config_id: string | null
    model: string | null
  }
}

export interface KnowledgeBaseStats {
  document_count: number
  ready_count: number
  processing_count: number
  failed_count: number
  chunk_count: number
  char_count: number
}

export interface ChunkItem {
  id: string
  document_id: string
  filename: string
  chunk_index: number
  page_no: number | null
  text: string
  token_count: number | null
  char_count: number
  created_at: string
}

export interface ChunkPage {
  items: ChunkItem[]
  total: number
  limit: number
  offset: number
}

export interface RetrievalHit {
  chunk_id: string
  document_id: string
  filename: string
  page_no: number | null
  chunk_index: number
  text: string
  distance: number | null
  vector_rank: number | null
  lexical_rank: number | null
  fused_score: number | null
  rerank_score: number | null
}

export interface RetrievalSearchResult {
  query: string
  mode: string
  hybrid_enabled: boolean
  rerank_enabled: boolean
  results: RetrievalHit[]
  timings: {
    vector_ms: number
    lexical_ms: number
    rerank_ms: number
    total_ms: number
  }
}

export interface EvalDataset {
  id: string
  name: string
  description: string
  question_count: number
  created_at: string
}

export interface EvalQuestion {
  id: string
  question: string
  relevant_document_ids: string[]
  evidence: string[]
}

export interface EvalDatasetDetail extends EvalDataset {
  questions: EvalQuestion[]
}

export type EvalMetrics = Record<string, number | string | boolean | null>

export interface EvalRun {
  id: string
  dataset_id: string
  kb_id: string
  status: string
  config: Record<string, unknown>
  metrics: EvalMetrics | null
  error_code: string | null
  progress_total: number
  progress_done: number
  prompt_tokens: number
  completion_tokens: number
  cost: number
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface EvalRunItem {
  id: string
  question_id: string
  question_text: string
  hit_rank: number | null
  reciprocal_rank: number
  evidence_hit: boolean | null
  latency_ms: number | null
  top_document_ids: string[]
  top_chunk_ids: string[]
  answer: string | null
  judge_score: number | null
  judge_faithful: boolean | null
  judge_reason: string | null
  judge_error: string | null
  answer_latency_ms: number | null
  prompt_tokens: number
  completion_tokens: number
  cost: number
  error_code: string | null
}

export interface EvalRunDetail extends EvalRun {
  items: EvalRunItem[]
}

export interface Webhook {
  id: string
  url: string
  events: string[]
  active: boolean
  created_at: string
}

export interface WebhookCreated extends Webhook {
  secret: string
}

export interface WebhookDelivery {
  id: string
  event: string
  status: string
  attempts: number
  response_status: number | null
  error: string | null
  next_attempt_at: string
  created_at: string
  delivered_at: string | null
}

export interface Project {
  id: string
  name: string
  description: string
  instructions: string
  default_provider_id: string | null
  default_model: string | null
  default_kb_id: string | null
  default_agent: boolean
  archived: boolean
  conversation_count: number
  owned: boolean
  created_at: string
  updated_at: string
}

export interface GenerationSettings {
  temperature?: number | null
  max_tokens?: number | null
  top_p?: number | null
}

export interface CustomAgent {
  id: string
  name: string
  description: string
  instructions: string
  category: string
  default_provider_id: string | null
  default_model: string | null
  default_kb_id: string | null
  tools: string[]
  plugin_ids: string[]
  visibility: 'private' | 'shared'
  enabled: boolean
  archived: boolean
  owned: boolean
  builtin: boolean
  conversation_count: number
  created_at: string | null
  updated_at: string | null
}

export interface Plugin {
  id: string
  slug: string
  name: string
  description: string
  category: string
  docs_url: string
  endpoint_url: string
  method: string
  auth_type: string
  parameters: {
    type?: string
    properties?: Record<string, { type?: string; description?: string }>
    required?: string[]
  }
  sensitive: boolean
  enabled: boolean
  timeout_seconds: number
  configured: boolean
  config_enabled: boolean
  credential_hint: string
  status: string
  last_error: string | null
  last_checked_at: string | null
}

export interface ConversationPlugin {
  plugin_id: string
  slug: string
  name: string
  sensitive: boolean
  confirmed_at: string | null
}

export interface PluginCall {
  id: string
  plugin_id: string
  conversation_id: string | null
  status: string
  request_summary: string
  response_summary: string
  latency_ms: number
  error_code: string | null
  created_at: string
}

export interface Conversation {
  id: string
  title: string
  provider_id: string
  model: string
  kb_id: string | null
  project_id?: string | null
  custom_agent_id?: string | null
  agent: boolean
  pinned?: boolean
  generation_settings?: GenerationSettings
  prompt_version_id?: string | null
  created_at: string
  updated_at?: string | null
  archived_at?: string | null
}

export interface PromptVersion {
  id: string
  version: number
  system_prompt: string
  variables: string[]
  created_at: string
}

export interface CollaborationStep {
  id: string
  role: 'planner' | 'worker' | 'critic' | string
  step_key: string
  status: string
  input_summary: string
  output_summary: string
  prompt_tokens: number
  completion_tokens: number
  cost: number
  error_code: string | null
  created_at: string
}

export interface CollaborationRun {
  id: string
  provider_id: string
  model: string
  kb_id: string | null
  status: string
  input_text: string
  plan: { id: string; agent: string; task: string }[] | null
  final_output: string
  rounds: number
  error_code: string | null
  cancel_requested_at: string | null
  prompt_tokens: number
  completion_tokens: number
  cost: number
  total_ms: number | null
  started_at: string
  finished_at: string | null
  steps: CollaborationStep[]
}

export interface WorkflowNodeDefinition {
  id: string
  type: 'llm' | 'kb_search' | 'tool' | 'agent' | 'condition' | 'parallel' | 'join'
  config: Record<string, unknown>
}

export interface WorkflowEdgeDefinition {
  from: string
  to: string
  when?: 'true' | 'false' | null
}

export interface WorkflowDefinition {
  nodes: WorkflowNodeDefinition[]
  edges: WorkflowEdgeDefinition[]
}

export interface WorkflowVersion {
  id: string
  version: number
  definition: WorkflowDefinition
  created_at: string
}

export interface Workflow {
  id: string
  name: string
  description: string
  versions: WorkflowVersion[]
  created_at: string
}

export interface WorkflowNodeRun {
  id: string
  node_id: string
  node_type: string
  status: string
  attempts: number
  input_summary: string
  output_summary: string
  error_code: string | null
  duration_ms: number | null
  created_at: string
}

export interface WorkflowRun {
  id: string
  workflow_id: string
  version_id: string
  kb_id: string | null
  status: string
  input_text: string
  error_code: string | null
  cancel_requested_at: string | null
  prompt_tokens: number
  completion_tokens: number
  cost: number
  total_ms: number | null
  started_at?: string
  finished_at: string | null
  nodes: WorkflowNodeRun[]
}

export interface RunAccepted {
  run_id: string
  status: string
}

export interface RunCancelResult {
  run_id: string
  status: string
  cancel_requested_at: string | null
}

export interface AdminWorkspace {
  id: string
  name: string
  plan: string
  is_personal: boolean
  member_count: number
  created_at: string
}

export interface AdminMember {
  user_id: string
  email: string
  role: string
  created_at: string
}

export interface AdminModel {
  id: string
  provider_id: string
  model_id: string
  display_name: string
  enabled: boolean
}

export interface AdminRunCounts {
  total: number
  failed: number
  failure_rate: number
}

export interface AdminRunSummary {
  workflows: AdminRunCounts
  collaborations: AdminRunCounts
}

export interface AdminUsage {
  start: string
  end: string
  group_by: string
  requests: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  total_cost: number
  unpriced_requests: number
  buckets: UsageCostBucket[]
}

export interface AuditLog {
  id: string
  actor_user_id: string | null
  actor_email: string | null
  action: string
  target_type: string
  target_id: string | null
  detail: Record<string, unknown> | null
  created_at: string
}

export interface PromptTemplate {
  id: string
  name: string
  description: string
  category: string
  favorite: boolean
  versions: PromptVersion[]
  created_at: string
}

export interface DashboardCounts {
  providers: number
  models: number
  conversations: number
  projects: number
  knowledge_bases: number
  agents: number
  plugins: number
  unread_notifications: number
  requests_30d: number
  tokens_30d: number
  cost_30d: number
}

export interface Dashboard {
  counts: DashboardCounts
  recent_conversations: Conversation[]
  recent_projects: { id: string; name: string; updated_at: string }[]
}

export interface FileItem {
  id: string
  filename: string
  mime: string
  size_bytes: number
  status: string
  error_code: string | null
  page_count: number | null
  kb_id: string
  kb_name: string
  created_at: string
}

export interface SearchResult {
  type: string
  id: string
  title: string
  subtitle: string
  href: string
}

export interface SearchResponse {
  query: string
  results: SearchResult[]
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

export interface MessageFeedback {
  message_id: string
  rating: 'up' | 'down'
  reason: string
  updated_at: string
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
  reply_to_message_id?: string | null
  created_at: string
  citations: Citation[]
  feedback?: MessageFeedback | null
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
  id: string
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
  plugins: ConversationPlugin[]
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

export interface UsageCostBucket extends UsageBucket {
  cost: number
  unpriced_requests: number
}

export interface UsageCost {
  start: string
  end: string
  group_by: string
  total_cost: number
  unpriced_requests: number
  buckets: UsageCostBucket[]
}

export interface UsageByKeyBucket {
  api_key_id: string | null
  name: string
  prefix: string | null
  requests: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: number
  unpriced_requests: number
}

export interface UsageByKey {
  start: string
  end: string
  total_requests: number
  total_cost: number
  unpriced_requests: number
  buckets: UsageByKeyBucket[]
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
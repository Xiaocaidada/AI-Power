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
  description: string
  created_at: string
}

export interface ChatAttachment {
  id: string
  filename: string
  mime: string
  size_bytes: number
  kind: 'document' | 'image'
  status: string
  error_code: string | null
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
    metadata_filter: Record<string, string>
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

export interface KnowledgeProcessAnalyticsRun {
  id: string
  document_id: string | null
  filename: string
  status: string
  error_code: string | null
  duration_ms: number | null
  chunk_count: number
  applied: boolean
  started_at: string
}

export interface KnowledgeProcessAnalytics {
  days: number
  total: number
  completed: number
  failed: number
  cancelled: number
  running: number
  success_rate: number
  avg_duration_ms: number
  p95_duration_ms: number
  avg_chunks: number
  applied_count: number
  pending_apply: number
  failure_codes: Record<string, number>
  recent: KnowledgeProcessAnalyticsRun[]
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
  chunk_meta?: Record<string, unknown>
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

export type EvalMetrics = Record<string, unknown>

export interface EvalRun {
  id: string
  dataset_id: string
  kb_id: string
  retrieval_workflow_version_id: string | null
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
  precision_at_5: number
  recall_at_5: number
  ndcg_at_5: number
  precision_at_10: number
  recall_at_10: number
  ndcg_at_10: number
  retrieval_mode: string | null
  retrieval_trace: KnowledgeRetrievalTestNode[]
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

export interface EvalNodeTiming {
  node_type: string
  runs: number
  failures: number
  avg_ms: number
  avg_count: number
}

export interface EvalQuestionInsight {
  question_id: string
  question_text: string
  hit_rank: number | null
  precision_at_5: number
  recall_at_5: number
  ndcg_at_5: number
  latency_ms: number | null
  retrieval_mode: string | null
  error_code: string | null
}

export interface EvalRunAnalysis {
  run: EvalRun
  node_timing: EvalNodeTiming[]
  worst_questions: EvalQuestionInsight[]
  missed_questions: EvalQuestionInsight[]
  slowest_questions: EvalQuestionInsight[]
}

export interface KnowledgeOptimization {
  id: string
  kb_id: string
  eval_run_id: string | null
  workflow_id: string | null
  base_version_id: string | null
  applied_version_id: string | null
  previous_binding_version_id: string | null
  status: 'proposed' | 'applied' | 'reverted' | 'dismissed' | string
  summary: string
  rationale: string
  suggestions: { title: string; detail: string }[]
  metrics_snapshot: EvalMetrics
  provider_id: string | null
  model: string | null
  error_code: string | null
  created_at: string
  applied_at: string | null
  reverted_at: string | null
}

export interface KnowledgeOptimizationDetail extends KnowledgeOptimization {
  proposed_definition: WorkflowDefinition | null
  diff: AgentBuilderDiff | null
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
  kb_ids: string[]
  default_custom_agent_id: string | null
  default_agent: boolean
  memory_enabled: boolean | null
  allow_global_memory: boolean
  allow_agent_writes: boolean
  archived: boolean
  conversation_count: number
  owned: boolean
  created_at: string
  updated_at: string
}

export interface AgentRun {
  id: string
  kind: 'chat' | 'workflow'
  title: string
  status: string
  input: string
  output: string
  model: string
  duration_ms: number | null
  error_code: string | null
  created_at: string
  href: string
}

export interface GenerationSettings {
  temperature?: number | null
  max_tokens?: number | null
  top_p?: number | null
}

export type AgentMode = 'autonomous' | 'workflow' | 'hybrid'

export interface CustomAgent {
  id: string
  name: string
  description: string
  instructions: string
  category: string
  mode: AgentMode
  icon: string
  cover_url: string
  welcome_message: string
  examples: string[]
  usage_instructions: string
  generation_settings: GenerationSettings
  default_provider_id: string | null
  default_model: string | null
  default_kb_id: string | null
  kb_ids: string[]
  tools: string[]
  plugin_ids: string[]
  workflow_id: string | null
  visibility: 'private' | 'shared'
  enabled: boolean
  memory_enabled: boolean
  memory_read_global: boolean
  memory_read_project: boolean
  memory_read_agent: boolean
  memory_write: boolean
  memory_write_scope: MemoryScopeType
  memory_write_mode: 'candidate' | 'create' | 'upsert'
  rating_avg: number
  rating_count: number
  archived: boolean
  owned: boolean
  builtin: boolean
  published: boolean
  featured: boolean
  public_slug: string | null
  allow_copy: boolean
  show_structure: boolean
  favorite: boolean
  favorite_count: number
  usage_count: number
  copy_count: number
  conversation_count: number
  created_at: string | null
  updated_at: string | null
}

export interface AgentPublishIn {
  slug: string
  allow_copy: boolean
  show_structure: boolean
}

export interface AgentMarketSummary {
  id: string
  slug: string
  name: string
  description: string
  icon: string
  cover_url: string
  category: string
  mode: AgentMode
  featured: boolean
  official: boolean
  publisher: string
  usage_count: number
  favorite_count: number
  copy_count: number
  rating_avg: number
  rating_count: number
  allow_copy: boolean
  published_at: string | null
}

export interface AgentFacetCount {
  value: string
  count: number
}

export interface AgentMarketFacets {
  total: number
  official: number
  featured: number
  categories: AgentFacetCount[]
  publishers: AgentFacetCount[]
}

export interface AgentBuiltinTool {
  name: string
  description: string
  parameters: Record<string, unknown>
}

export interface AgentMcpServer {
  id: string
  name: string
  description: string
}

export interface AgentToolCatalog {
  builtin: AgentBuiltinTool[]
  mcp_servers: AgentMcpServer[]
}

export interface AgentMcpTool {
  name: string
  description: string
  input_schema: Record<string, unknown>
  ref: string
}

export interface AgentToolTestResult {
  ok: boolean
  output: string
  error_code: string | null
  error: string | null
  duration_ms: number
}

export interface AgentReview {
  id: string
  rating: number
  content: string
  author: string
  created_at: string
  updated_at: string
}

export interface AgentReviewList {
  rating_avg: number
  rating_count: number
  reviews: AgentReview[]
}

export type AgentReportReason = 'spam' | 'abuse' | 'copyright' | 'misleading' | 'other'

export interface AdminAgentReview {
  id: string
  agent_id: string
  agent_name: string
  author: string
  rating: number
  content: string
  status: string
  created_at: string
  updated_at: string
}

export interface AgentReport {
  id: string
  agent_id: string
  agent_name: string
  reporter: string
  reason: string
  detail: string
  status: string
  resolution: string
  created_at: string
  handled_at: string | null
}

export interface WorkflowReview {
  id: string
  run_id: string
  node_id: string
  status: string
  prompt: string
  decision: string
  comment: string
  output: string
  reviewer_user_id: string | null
  created_at: string
  expires_at: string | null
  resolved_at: string | null
}

export type MemoryScopeType = 'global' | 'project' | 'agent'
export type MemoryCategory =
  | 'fact'
  | 'preference'
  | 'profile'
  | 'project'
  | 'technical'
  | 'experience'
  | 'decision'
  | 'relation'
  | 'summary'
export type MemoryStatus =
  | 'candidate'
  | 'active'
  | 'conflict'
  | 'expired'
  | 'archived'
  | 'rejected'

export interface AgentMemory {
  id: string
  agent_id: string | null
  project_id: string | null
  scope: 'user' | 'workspace'
  scope_type: MemoryScopeType
  kind: string
  category: MemoryCategory
  status: MemoryStatus
  title: string
  content: string
  importance: number
  source: string
  source_type: string
  source_id: string | null
  source_ref: Record<string, unknown>
  confidence: number
  sensitivity: 'normal' | 'sensitive'
  enabled: boolean
  pinned: boolean
  favorite: boolean
  tags: string[]
  valid_until: string | null
  retention_days?: number | null
  use_count: number
  version: number
  metadata: Record<string, unknown>
  last_used_at: string | null
  created_at: string
  updated_at: string
}

export interface MemoryCandidate {
  id: string
  project_id: string | null
  agent_id: string | null
  target_memory_id: string | null
  source_type: string
  source_id: string | null
  source_ref: Record<string, unknown>
  extracted_by: string | null
  suggested_action: string
  category: MemoryCategory
  scope_type: MemoryScopeType
  title: string
  content: string
  tags: string[]
  confidence: number
  sensitivity: string
  status: string
  reason: string
  created_at: string
  reviewed_at: string | null
}

export interface MemoryCompleteness {
  average_score: number
  complete: number
  partial: number
  sparse: number
}

export interface MemoryUsageModel {
  provider_id: string
  model: string
  count: number
  injected_chars: number
}

export interface MemoryUsageRef {
  agent_id?: string | null
  project_id?: string | null
  context_id?: string | null
  count: number
}

export interface MemoryStats {
  total: number
  active: number
  pending: number
  candidates_pending?: number
  conflict: number
  expired: number
  archived: number
  by_category: Record<string, number>
  by_scope: Record<string, number>
  by_status?: Record<string, number>
  by_source?: Record<string, number>
  completeness?: MemoryCompleteness
  retention_days?: number | null
  expiring_soon?: number
  stale?: number
  active_chars?: number
  usage_total?: number
  usage_chars?: number
  usage_by_model?: MemoryUsageModel[]
  usage_by_context?: Record<string, number>
  usage_by_agent?: MemoryUsageRef[]
  usage_by_project?: MemoryUsageRef[]
  usage_by_conversation?: MemoryUsageRef[]
  recent: AgentMemory[]
  top_used: AgentMemory[]
}

export interface MemoryLifecycleItem {
  id: string
  title: string
  updated_at: string
  retention_days: number
}

export interface MemoryLifecycle {
  retention_days: number | null
  expiring_count: number
  items: MemoryLifecycleItem[]
}

export interface MemoryDiffChange {
  field: string
  before: unknown
  after: unknown
}

export interface MemoryVersionDiff {
  from_version: number
  to_version: number
  from_created_at: string
  to_created_at: string
  from_reason: string
  to_reason: string
  changes: MemoryDiffChange[]
  content_diff: string
  risk_flags: string[]
}

export interface MemorySettings {
  enabled: boolean
  auto_extract: boolean
  auto_save: boolean
  require_confirmation: boolean
  allowed_categories: string[]
  allow_project_extract: boolean
  allow_agent_extract: boolean
  allow_cross_model: boolean
  max_inject_items: number
  max_inject_chars: number
  blocked_topics: string[]
  retention_days: number | null
  updated_at: string
}

export interface MemoryVersion {
  id: string
  version: number
  snapshot: Record<string, unknown>
  changed_by: string | null
  change_reason: string
  created_at: string
}

export interface MemoryRelation {
  id: string
  from_type: string
  from_id: string
  to_type: string
  to_id: string
  relation_type: string
  confidence: number
  basis: string
  source: string
  created_at: string
}

export interface MemoryGraphNode {
  id: string
  type: 'memory' | 'project' | 'agent' | 'document'
  label: string
  memory_id: string | null
  ref_id: string | null
  category: MemoryCategory | null
  scope_type: MemoryScopeType | null
  status: MemoryStatus | null
  pinned: boolean
  importance: number | null
}

export interface MemoryGraphEdge {
  id: string
  source: string
  target: string
  relation_type: string
  confidence: number
  basis: string
  source_kind: string
}

export interface MemoryGraphStats {
  memories: number
  external: number
  relations: number
  orphans: number
}

export interface MemoryGraph {
  nodes: MemoryGraphNode[]
  edges: MemoryGraphEdge[]
  stats: MemoryGraphStats
}

export interface MemoryQualityAnalysis {
  total: number
  duplicates: number
  duplicate_groups: string[][]
  conflicts: number
  expired: number
  unused: number
  missing_source: number
  incomplete: number
  orphans: number
}

export type MemoryOptimizationKind =
  | 'merge_duplicates'
  | 'resolve_conflict'
  | 'expire_memory'
  | 'archive_memory'
  | 'recategorize'

export interface MemoryOptimization {
  id: string
  kind: string
  status: 'pending' | 'applied' | 'dismissed' | 'rolled_back'
  title: string
  reason: string
  expected_effect: string
  memory_ids: string[]
  payload: Record<string, unknown>
  applied_at: string | null
  rolled_back_at: string | null
  created_at: string
}

export interface MemoryQuality {
  analysis: MemoryQualityAnalysis
  suggestions: MemoryOptimization[]
}

export interface MemoryEvalCase {
  id: string
  name: string
  query: string
  expected_memory_ids: string[]
  project_id: string | null
  agent_id: string | null
  notes: string
  created_at: string
  updated_at: string
}

export interface MemoryEvalRun {
  id: string
  status: string
  cases_count: number
  metrics: Record<string, number>
  results: {
    case_id: string
    name: string
    query: string
    expected_ids: string[]
    retrieved_ids: string[]
    hits: string[]
    precision: number
    recall: number
    mrr: number
  }[]
  duration_ms: number
  created_at: string
}

export interface MemoryUsage {
  id: string
  memory_id: string
  memory_title: string
  context_type: string
  context_id: string | null
  provider_id: string | null
  model: string | null
  relevance: number | null
  injected_chars: number
  created_at: string
}

export interface McpServer {
  id: string
  name: string
  description: string
  endpoint_url: string
  enabled: boolean
  timeout_seconds: number
  auth_hint: string
  created_at: string
  updated_at: string
}

export interface DatabaseConnection {
  id: string
  name: string
  description: string
  enabled: boolean
  max_rows: number
  timeout_seconds: number
  dsn_hint: string
  created_at: string
  updated_at: string
}

export interface DatabaseConnectionOption {
  id: string
  name: string
  description: string
}

export interface McpServerOption {
  id: string
  name: string
  description: string
}

export interface McpResource {
  uri: string
  name: string
  description: string
  mime_type: string
}

export interface McpPrompt {
  name: string
  description: string
  arguments: unknown[]
}

export interface McpTool {
  name: string
  description: string
  input_schema: Record<string, unknown>
}

export interface AgentMarketDetail extends AgentMarketSummary {
  welcome_message: string
  examples: string[]
  usage_instructions: string
  tools: string[]
  model_hint: string
  kb_requirements: string[]
  plugin_requirements: string[]
  instructions?: string | null
  workflow?: WorkflowDefinition | null
}

export interface WorkflowCatalogField {
  name: string
  label: string
  kind:
    | 'text'
    | 'textarea'
    | 'number'
    | 'select'
    | 'json'
    | 'provider'
    | 'model'
    | 'agent'
    | 'kb_multi'
    | 'mcp_server'
    | 'db_connection'
    | 'project'
    | 'boolean'
  required?: boolean
  hint?: string
  options?: string[]
}

export interface WorkflowCatalogNode {
  type: WorkflowNodeDefinition['type']
  label: string
  description: string
  icon: string
  config_fields: WorkflowCatalogField[]
}

export interface WorkflowTemplate {
  id?: string
  name: string
  description: string
  icon?: string
  definition: WorkflowDefinition
}

export interface WorkflowCatalog {
  nodes: WorkflowCatalogNode[]
  limits: { max_nodes: number; max_kbs?: number; linear?: boolean }
  variables: Record<string, string>
  templates?: WorkflowTemplate[]
}

export interface AgentBuilderResult {
  definition: WorkflowDefinition
  summary: string
  missing_resources: string[]
  provider_id: string
  model: string
}

export interface AgentBuilderNodeChange {
  field: string
  before: unknown
  after: unknown
}

export interface AgentBuilderNodeDiff {
  id: string
  type: string
  changes: AgentBuilderNodeChange[]
}

export interface AgentBuilderDiff {
  added_nodes: { id: string; type: string }[]
  removed_nodes: { id: string; type: string }[]
  updated_nodes: AgentBuilderNodeDiff[]
  added_edges: { from: string; to: string; when?: string | null }[]
  removed_edges: { from: string; to: string; when?: string | null }[]
}

export interface AgentBuilderMessage {
  role: 'user' | 'assistant'
  kind: string
  content: string
  summary?: string
  definition?: WorkflowDefinition | null
  diff?: AgentBuilderDiff | null
  missing_resources?: string[]
  suggestions?: string[]
  clarification?: string | null
  run_id?: string | null
  created_at?: string
}

export interface AgentBuilderSession {
  id: string
  scope: 'agent' | 'knowledge_process' | 'knowledge_retrieval'
  agent_id: string | null
  workflow_id: string | null
  provider_id: string
  model: string
  messages: AgentBuilderMessage[]
  draft_definition: WorkflowDefinition
  created_at: string
  updated_at: string
}

export interface AgentBuilderTurn {
  session_id: string
  message: string
  definition: WorkflowDefinition | null
  diff: AgentBuilderDiff | null
  missing_resources: string[]
  suggestions: string[]
  clarification?: string | null
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
  kb_ids?: string[]
  project_id?: string | null
  custom_agent_id?: string | null
  agent: boolean
  pinned?: boolean
  memory_enabled?: boolean | null
  excluded_memory_ids?: string[]
  generation_settings?: GenerationSettings
  prompt_version_id?: string | null
  created_at: string
  updated_at?: string | null
  archived_at?: string | null
}

export interface PromptVariableDefinition {
  name: string
  description: string
  required: boolean
  default: string
}

export interface PromptDiffLine {
  type: 'equal' | 'insert' | 'delete'
  old_line: number | null
  new_line: number | null
  text: string
}

export interface PromptDiff {
  from_version: number
  to_version: number
  system: PromptDiffLine[]
  user: PromptDiffLine[]
}

export interface PromptVersion {
  id: string
  version: number
  system_prompt: string
  user_prompt: string
  variables: string[]
  variable_definitions: PromptVariableDefinition[]
  parameters: GenerationSettings
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
  type:
    | 'start'
    | 'llm'
    | 'kb_search'
    | 'tool'
    | 'agent'
    | 'condition'
    | 'parallel'
    | 'join'
    | 'output'
    | 'review'
    | 'loop'
    | 'http'
    | 'mcp'
    | 'memory_read'
    | 'memory_write'
    | 'code'
    | 'database'
    | 'mcp_resource'
    | 'mcp_prompt'
    | 'parse_document'
    | 'clean_text'
    | 'chunk_text'
    | 'embed_chunks'
    | 'index_knowledge'
    | 'rewrite_query'
    | 'vector_search'
    | 'lexical_search'
    | 'hybrid_search'
    | 'rerank'
    | 'top_k'
    | 'context'
  config: Record<string, unknown>
  ui?: { x: number; y: number } | null
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
  kind: 'agent' | 'knowledge_process' | 'knowledge_retrieval'
  versions: WorkflowVersion[]
  draft_definition?: WorkflowDefinition | null
  draft_saved_at?: string | null
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

export interface WorkflowNodeDebugResult {
  run_id: string
  node_id: string
  node_type: string
  status: string
  output: string
  input_summary: string
  error_code: string | null
  duration_ms: number
  node_run_id: string | null
}

export interface KnowledgeProcessBinding {
  workflow_version_id: string | null
  workflow_id: string | null
  version: number | null
  kind: string
  name: string
}

export interface KnowledgeProcessArtifact {
  node_id: string
  kind: string
  payload: Record<string, unknown>
}

export interface KnowledgeProcessDraft {
  chunk_index: number
  page_no: number | null
  text: string
  meta: Record<string, unknown>
  embedded: boolean
}

export interface KnowledgeRetrievalTestNode {
  node_id: string
  node_type: string
  status: string
  duration_ms: number
  count: number
  error_code: string | null
}

export interface KnowledgeRetrievalTestResult {
  query: string
  rewritten_query: string
  mode: string
  context: string
  results: RetrievalHit[]
  citations: Record<string, unknown>[]
  nodes: KnowledgeRetrievalTestNode[]
  timings: Record<string, number>
}

export interface KnowledgeProcessPreview {
  run: WorkflowRun
  artifacts: KnowledgeProcessArtifact[]
  drafts: KnowledgeProcessDraft[]
  draft_count: number
  applied: boolean
}

export interface WorkflowRun {
  id: string
  workflow_id: string
  version_id: string
  kb_id: string | null
  status: string
  input_text: string
  input_payload: Record<string, unknown>
  output_payload: Record<string, unknown>
  applied_at: string | null
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
  scope: 'workspace' | 'platform'
  favorite: boolean
  versions: PromptVersion[]
  created_at: string
}

export interface PromptExperimentOutput {
  id: string
  provider_id: string
  model: string
  status: string
  content: string
  prompt_tokens: number | null
  completion_tokens: number | null
  cost: number
  ttft_ms: number | null
  total_ms: number | null
  error_code: string | null
}

export interface PromptExperiment {
  id: string
  template_id: string | null
  version_id: string | null
  system_prompt: string
  user_prompt: string
  variables: Record<string, string>
  parameters: GenerationSettings
  rating: string | null
  note: string
  created_at: string
  outputs: PromptExperimentOutput[]
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
  tags?: string[]
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

export interface MessageMemoryRef {
  id: string
  title: string
  category: string
  scope_type: string
  relevance: number
  injected_chars: number
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
  memory_refs?: MessageMemoryRef[]
  reply_to_message_id?: string | null
  created_at: string
  citations: Citation[]
  feedback?: MessageFeedback | null
  attachments?: ChatAttachment[]
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

export interface QuotaKnowledge {
  max_kbs: number
  kb_count: number
  max_documents_per_kb: number
  max_kb_bytes: number
  kb_bytes: number
}

export interface QuotaMemory {
  max_memories: number
  memory_count: number
}

export interface QuotaSummary {
  plan: string
  requests: QuotaWindow
  tokens: QuotaWindow
  max_keys: number
  active_keys: number
  knowledge: QuotaKnowledge
  memory: QuotaMemory
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
  tags?: string[]
  folder?: string
  doc_metadata?: Record<string, string>
  source_url?: string | null
  created_at: string
}

export interface DocumentFolder {
  folder: string
  count: number
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

export interface ModelEvalQuestion {
  id: string
  question: string
  reference_answer: string
  scoring_criteria: string
  expected_keywords: string[]
  regex: string
  sort_order: number
}

export interface ModelEvalDataset {
  id: string
  name: string
  description: string
  question_count: number
  created_at: string
  questions?: ModelEvalQuestion[]
}

export interface ModelEvalScore {
  method: string
  score: number | null
  passed: boolean | null
  reason: string
  judge_provider_id: string | null
  judge_model: string | null
}

export interface ModelEvalItem {
  id: string
  question_id: string
  provider_id: string
  model: string
  question: string
  answer: string
  status: string
  error_code: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  cost: number
  ttft_ms: number | null
  latency_ms: number | null
  scores: ModelEvalScore[]
}

export interface ModelEvalRun {
  id: string
  dataset_id: string
  name: string
  status: string
  config: Record<string, unknown>
  metrics: Record<string, unknown> | null
  error_code: string | null
  progress_total: number
  progress_done: number
  progress_failed: number
  progress_running: number
  current_model: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  items?: ModelEvalItem[]
}

export interface ArenaResponse {
  id: string
  position: number
  label: string
  provider_id: string | null
  model: string | null
  status: string
  content: string
  prompt_tokens: number | null
  completion_tokens: number | null
  cost: number
  ttft_ms: number | null
  total_ms: number | null
  error_code: string | null
  feedback: 'helpful' | 'unhelpful' | null
  attempt: number
}

export interface ArenaRound {
  id: string
  prompt: string
  blind: boolean
  revealed: boolean
  vote_response_id: string | null
  vote_reason: string
  generation_settings: GenerationSettings
  created_at: string
  responses: ArenaResponse[]
}

export interface UsageRecentItem {
  id: string
  source: string
  provider_id: string | null
  model: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number
  cost: number
  status: string | null
  conversation_id: string | null
  created_at: string
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
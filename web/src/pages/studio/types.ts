import { generationDraft, type GenerationDraft } from '../../lib/agentSettings'
import type {
  AgentMode,
  CustomAgent,
  KnowledgeBase,
  DatabaseConnectionOption,
  McpServerOption,
  Plugin,
  Project,
  WorkflowDefinition,
  WorkflowNodeDefinition,
} from '../../lib/types'

export interface StudioNodeData extends Record<string, unknown> {
  nodeType: WorkflowNodeDefinition['type']
  label: string
  config: Record<string, unknown>
}

export interface ModelChoice {
  provider_id: string
  model: string
  label: string
}

export interface StudioAgentDraft extends GenerationDraft {
  name: string
  description: string
  instructions: string
  category: string
  mode: AgentMode
  icon: string
  coverUrl: string
  welcomeMessage: string
  examples: string
  usageInstructions: string
  providerChoice: string
  kbIds: string[]
  tools: string[]
  pluginIds: string[]
  visibility: 'private' | 'shared'
  allowCopy: boolean
  showStructure: boolean
  memoryEnabled: boolean
  attachmentsEnabled: boolean
  memoryReadGlobal: boolean
  memoryReadProject: boolean
  memoryReadAgent: boolean
  memoryWrite: boolean
  memoryWriteScope: 'global' | 'project' | 'agent'
  memoryWriteMode: 'candidate' | 'create' | 'upsert'
}

export interface StudioResources {
  models: ModelChoice[]
  knowledgeBases: KnowledgeBase[]
  agents: CustomAgent[]
  plugins: Plugin[]
  projects: Project[]
  mcpServers: McpServerOption[]
  databaseConnections: DatabaseConnectionOption[]
}

export function draftFromAgent(agent: CustomAgent): StudioAgentDraft {
  return {
    ...generationDraft(agent.generation_settings ?? {}),
    name: agent.name,
    description: agent.description,
    instructions: agent.instructions,
    category: agent.category,
    mode: agent.mode,
    icon: agent.icon || '🤖',
    coverUrl: agent.cover_url ?? '',
    welcomeMessage: agent.welcome_message,
    examples: agent.examples.join('\n'),
    usageInstructions: agent.usage_instructions,
    providerChoice:
      agent.default_provider_id === null
        ? ''
        : agent.default_provider_id === 'auto'
          ? 'auto'
          : `m:${agent.default_provider_id}:${agent.default_model ?? ''}`,
    kbIds: agent.kb_ids,
    tools: agent.tools,
    pluginIds: agent.plugin_ids,
    visibility: agent.visibility,
    allowCopy: agent.allow_copy,
    showStructure: agent.show_structure,
    memoryEnabled: agent.memory_enabled,
    attachmentsEnabled: agent.attachments_enabled,
    memoryReadGlobal: agent.memory_read_global,
    memoryReadProject: agent.memory_read_project,
    memoryReadAgent: agent.memory_read_agent,
    memoryWrite: agent.memory_write,
    memoryWriteScope: agent.memory_write_scope,
    memoryWriteMode: agent.memory_write_mode,
  }
}

export function parseProviderChoice(choice: string): {
  provider_id: string | null
  model: string | null
} {
  if (choice === 'auto') return { provider_id: 'auto', model: 'auto' }
  if (choice.startsWith('m:')) {
    const [, provider, ...rest] = choice.split(':')
    return { provider_id: provider, model: rest.join(':') }
  }
  return { provider_id: null, model: null }
}

export function emptyDefinition(): WorkflowDefinition {
  return {
    nodes: [
      { id: 'start', type: 'start', config: {}, ui: { x: 80, y: 160 } },
      { id: 'out', type: 'output', config: {}, ui: { x: 520, y: 160 } },
    ],
    edges: [{ from: 'start', to: 'out' }],
  }
}

export function normalizeDefinition(
  definition: WorkflowDefinition | null | undefined,
): WorkflowDefinition {
  if (definition === null || definition === undefined || definition.nodes.length === 0) {
    return emptyDefinition()
  }
  return definition
}
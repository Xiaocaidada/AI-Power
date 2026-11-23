import type {
  AgentMode,
  CustomAgent,
  KnowledgeBase,
  Plugin,
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

export interface StudioAgentDraft {
  name: string
  description: string
  instructions: string
  category: string
  mode: AgentMode
  icon: string
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
}

export interface StudioResources {
  models: ModelChoice[]
  knowledgeBases: KnowledgeBase[]
  agents: CustomAgent[]
  plugins: Plugin[]
}

export function draftFromAgent(agent: CustomAgent): StudioAgentDraft {
  return {
    name: agent.name,
    description: agent.description,
    instructions: agent.instructions,
    category: agent.category,
    mode: agent.mode,
    icon: agent.icon || '🤖',
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